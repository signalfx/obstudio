package mcp

import (
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

type tokenUsageRepositoryFilter struct {
	RepositoryName string `json:"repositoryName,omitempty"`
	RepositoryPath string `json:"repositoryPath,omitempty"`
	workspacePath  string
}

type tokenUsageRepositoryCoverage struct {
	CandidateTaskCount     int `json:"candidateTaskCount"`
	CorrelatedTaskCount    int `json:"correlatedTaskCount"`
	TaskCorrelatedCount    int `json:"taskCorrelatedCount"`
	SessionCorrelatedCount int `json:"sessionCorrelatedCount"`
	AmbiguousTaskCount     int `json:"ambiguousTaskCount"`
	UnattributedTaskCount  int `json:"unattributedTaskCount"`
	MatchedTaskCount       int `json:"matchedTaskCount"`
}

type providerRepositoryIdentity struct {
	repositoryName string
	repositoryPath string
	workspacePath  string
}

func appendUniqueProviderRepositoryIdentity(
	identities []providerRepositoryIdentity,
	candidate providerRepositoryIdentity,
) []providerRepositoryIdentity {
	if candidate.repositoryName == "" {
		return identities
	}
	for _, identity := range identities {
		if sameProviderRepositoryIdentity(identity, candidate) {
			return identities
		}
	}
	return append(identities, candidate)
}

func sameProviderRepositoryIdentity(left, right providerRepositoryIdentity) bool {
	return strings.EqualFold(strings.TrimSpace(left.repositoryName), strings.TrimSpace(right.repositoryName)) &&
		sameOptionalRepositoryPath(left.repositoryPath, right.repositoryPath) &&
		sameOptionalRepositoryPath(left.workspacePath, right.workspacePath)
}

func repositoryFilterFromArgs(args map[string]any) *tokenUsageRepositoryFilter {
	name := strings.TrimSpace(strArg(args, "repositoryName"))
	path := strings.TrimSpace(strArg(args, "repositoryPath"))
	if name == "" && path == "" {
		return nil
	}
	filter := &tokenUsageRepositoryFilter{RepositoryName: name}
	if path != "" {
		identity := repositoryIdentityFromWorkingDirectory(path)
		filter.RepositoryPath = identity.repositoryPath
		filter.workspacePath = identity.workspacePath
		if filter.RepositoryPath == "" {
			filter.RepositoryPath = cleanRepositoryPath(path)
		}
	}
	return filter
}

func hasRepositoryFilter(args map[string]any) bool {
	return strings.TrimSpace(strArg(args, "repositoryName")) != "" ||
		strings.TrimSpace(strArg(args, "repositoryPath")) != ""
}

func correlateAndFilterProviderTasks(
	tasks []providerLogTaskBuild,
	correlations []store.ProviderRepositoryCorrelation,
	filter *tokenUsageRepositoryFilter,
) ([]providerLogTaskBuild, tokenUsageRepositoryCoverage) {
	return correlateAndFilterProviderTasksWithResolver(tasks, correlations, filter, nil)
}

func correlateAndFilterProviderTasksWithResolver(
	tasks []providerLogTaskBuild,
	correlations []store.ProviderRepositoryCorrelation,
	filter *tokenUsageRepositoryFilter,
	modeResolver RepositoryCorrelationModeResolver,
) ([]providerLogTaskBuild, tokenUsageRepositoryCoverage) {
	return correlateAndFilterProviderTasksWithResolverAndWatermark(
		tasks,
		correlations,
		filter,
		modeResolver,
		time.Time{},
	)
}

func correlateAndFilterProviderTasksWithResolverAndWatermark(
	tasks []providerLogTaskBuild,
	correlations []store.ProviderRepositoryCorrelation,
	filter *tokenUsageRepositoryFilter,
	modeResolver RepositoryCorrelationModeResolver,
	unavailableThrough time.Time,
) ([]providerLogTaskBuild, tokenUsageRepositoryCoverage) {
	coverage := tokenUsageRepositoryCoverage{CandidateTaskCount: len(tasks)}
	filtered := make([]providerLogTaskBuild, 0, len(tasks))
	configuredModes := make(map[string]string)
	for _, built := range tasks {
		configuredMode, ok := configuredModes[built.task.Provider]
		if !ok && modeResolver != nil {
			configuredMode = normalizeResolvedRepositoryCorrelationMode(modeResolver(built.task.Provider))
			if configuredMode == "" {
				configuredMode = "off"
			}
			configuredModes[built.task.Provider] = configuredMode
		}
		applyProviderRepositoryCorrelationWithWatermark(
			&built.task,
			correlations,
			configuredMode,
			unavailableThrough,
		)
		switch built.task.RepositoryCorrelationStatus {
		case "task_correlated":
			coverage.CorrelatedTaskCount++
			coverage.TaskCorrelatedCount++
		case "session_correlated":
			coverage.CorrelatedTaskCount++
			coverage.SessionCorrelatedCount++
		case "ambiguous":
			coverage.AmbiguousTaskCount++
		default:
			coverage.UnattributedTaskCount++
		}
		if !taskMatchesRepositoryFilter(built.task, filter) {
			continue
		}
		coverage.MatchedTaskCount++
		filtered = append(filtered, built)
	}
	return filtered, coverage
}

func normalizeResolvedRepositoryCorrelationMode(raw string) string {
	switch mode := strings.ToLower(strings.TrimSpace(raw)); mode {
	case "off", "name", "path":
		return mode
	default:
		return ""
	}
}

func applyProviderRepositoryCorrelation(
	task *tokenUsageTask,
	correlations []store.ProviderRepositoryCorrelation,
	configuredMode string,
) {
	applyProviderRepositoryCorrelationWithWatermark(
		task,
		correlations,
		configuredMode,
		time.Time{},
	)
}

func applyProviderRepositoryCorrelationWithWatermark(
	task *tokenUsageTask,
	correlations []store.ProviderRepositoryCorrelation,
	configuredMode string,
	unavailableThrough time.Time,
) {
	if configuredMode == "off" {
		clearTaskRepositoryCorrelation(task)
		return
	}
	if task.RepositoryCorrelationStatus == "ambiguous" {
		task.RepositoryName = ""
		task.RepositoryPath = ""
		task.WorkspacePath = ""
		task.RepositoryCorrelationSource = ""
		return
	}
	exact := make([]store.ProviderRepositoryCorrelation, 0)
	session := make([]store.ProviderRepositoryCorrelation, 0)
	taskTime := parseTokenUsageTime(task.StartTime)
	if taskTime.IsZero() {
		taskTime = parseTokenUsageTime(task.EndTime)
	}
	taskEndTime := parseTokenUsageTime(task.EndTime)
	sessionAggregate := task.Provider == "claude" && task.TaskKind == "session"
	for _, correlation := range correlations {
		if correlation.Provider != task.Provider {
			continue
		}
		if correlation.TaskID != "" && repositoryCorrelationMatchesTask(correlation.TaskID, *task) {
			exact = append(exact, correlation)
			continue
		}
		if correlation.ConversationID == "" || task.ConversationID == "" ||
			!strings.EqualFold(correlation.ConversationID, task.ConversationID) {
			continue
		}
		if !correlation.ObservedAt.IsZero() {
			if sessionAggregate {
				if !taskEndTime.IsZero() && correlation.ObservedAt.After(taskEndTime) {
					continue
				}
			} else if !taskTime.IsZero() && correlation.ObservedAt.After(taskTime) {
				continue
			}
		}
		session = append(session, correlation)
	}
	if task.RepositoryName != "" {
		applyNativeRepositoryCorrelationMode(task, exact, session, configuredMode)
		if task.RepositoryName == "" {
			task.RepositoryCorrelationStatus = "unknown"
			task.RepositoryCorrelationSource = ""
			return
		}
		if task.RepositoryCorrelationStatus == "" {
			task.RepositoryCorrelationStatus = "task_correlated"
		}
		if task.RepositoryCorrelationSource == "" {
			task.RepositoryCorrelationSource = "provider_task_span"
		}
		return
	}
	if len(exact) > 0 {
		applySelectedRepositoryCorrelation(task, exact, "task_correlated", false, configuredMode)
		return
	}
	if !unavailableThrough.IsZero() &&
		(taskTime.IsZero() || !taskTime.After(unavailableThrough)) {
		task.RepositoryCorrelationStatus = "unknown"
		return
	}
	if len(session) > 0 {
		applySelectedRepositoryCorrelation(task, session, "session_correlated", sessionAggregate, configuredMode)
		return
	}
	task.RepositoryCorrelationStatus = "unknown"
}

func applyNativeRepositoryCorrelationMode(
	task *tokenUsageTask,
	exact []store.ProviderRepositoryCorrelation,
	session []store.ProviderRepositoryCorrelation,
	configuredMode string,
) {
	candidates := session
	if len(exact) > 0 {
		candidates = exact
	}
	mode := configuredMode
	if mode == "" && len(candidates) > 0 {
		sort.SliceStable(candidates, func(i, j int) bool {
			return candidates[i].ObservedAt.Before(candidates[j].ObservedAt)
		})
		mode = candidates[len(candidates)-1].Mode
	}
	applyRepositoryCorrelationMode(task, mode)
}

func clearTaskRepositoryCorrelation(task *tokenUsageTask) {
	task.RepositoryName = ""
	task.RepositoryPath = ""
	task.WorkspacePath = ""
	task.RepositoryCorrelationStatus = "unknown"
	task.RepositoryCorrelationSource = ""
}

func applyRepositoryCorrelationMode(task *tokenUsageTask, mode string) {
	switch mode {
	case "off":
		clearTaskRepositoryCorrelation(task)
	case "name":
		task.RepositoryPath = ""
		task.WorkspacePath = ""
	}
}

func repositoryCorrelationMatchesTask(correlationTaskID string, task tokenUsageTask) bool {
	for _, candidate := range []string{task.TaskID, task.TurnID, task.PromptID} {
		if candidate != "" && strings.EqualFold(correlationTaskID, candidate) {
			return true
		}
	}
	return false
}

func applySelectedRepositoryCorrelation(
	task *tokenUsageTask,
	candidates []store.ProviderRepositoryCorrelation,
	status string,
	requireConsistentIdentity bool,
	configuredMode string,
) {
	sort.SliceStable(candidates, func(i, j int) bool {
		return candidates[i].ObservedAt.Before(candidates[j].ObservedAt)
	})
	selected := candidates[len(candidates)-1]
	for index := len(candidates) - 2; index >= 0; index-- {
		candidate := candidates[index]
		if !requireConsistentIdentity && !candidate.ObservedAt.Equal(selected.ObservedAt) {
			break
		}
		if !sameRepositoryCorrelationIdentityForMode(candidate, selected, configuredMode) {
			task.RepositoryCorrelationStatus = "ambiguous"
			return
		}
	}
	task.RepositoryName = selected.RepositoryName
	task.RepositoryPath = selected.RepositoryPath
	task.WorkspacePath = selected.WorkspacePath
	task.RepositoryCorrelationStatus = status
	task.RepositoryCorrelationSource = selected.Source
	mode := configuredMode
	if mode == "" {
		mode = selected.Mode
	}
	applyRepositoryCorrelationMode(task, mode)
}

func sameRepositoryCorrelationIdentityForMode(
	left, right store.ProviderRepositoryCorrelation,
	configuredMode string,
) bool {
	if configuredMode == "name" {
		return strings.EqualFold(strings.TrimSpace(left.RepositoryName), strings.TrimSpace(right.RepositoryName))
	}
	return sameRepositoryCorrelationIdentity(left, right)
}

func sameRepositoryCorrelationIdentity(left, right store.ProviderRepositoryCorrelation) bool {
	return sameOptionalRepositoryPath(left.RepositoryPath, right.RepositoryPath) &&
		sameOptionalRepositoryPath(left.WorkspacePath, right.WorkspacePath) &&
		strings.EqualFold(strings.TrimSpace(left.RepositoryName), strings.TrimSpace(right.RepositoryName))
}

func sameOptionalRepositoryPath(left, right string) bool {
	if strings.TrimSpace(left) == "" || strings.TrimSpace(right) == "" {
		return strings.TrimSpace(left) == strings.TrimSpace(right)
	}
	return sameRepositoryPath(left, right)
}

func taskMatchesRepositoryFilter(task tokenUsageTask, filter *tokenUsageRepositoryFilter) bool {
	if filter == nil {
		return true
	}
	if task.RepositoryCorrelationStatus == "ambiguous" || task.RepositoryCorrelationStatus == "unknown" {
		return false
	}
	if filter.RepositoryName != "" && !strings.EqualFold(filter.RepositoryName, task.RepositoryName) {
		return false
	}
	if filter.RepositoryPath != "" &&
		!sameRepositoryPath(filter.RepositoryPath, task.RepositoryPath) &&
		!sameRepositoryPath(filter.RepositoryPath, task.WorkspacePath) {
		return false
	}
	if filter.workspacePath != "" &&
		!sameRepositoryPath(filter.workspacePath, filter.RepositoryPath) &&
		!sameRepositoryPath(filter.workspacePath, task.WorkspacePath) {
		return false
	}
	return true
}

func repositoryCorrelationStatus(coverage tokenUsageRepositoryCoverage) string {
	if coverage.CandidateTaskCount == 0 {
		return "unknown"
	}
	if coverage.AmbiguousTaskCount > 0 {
		return "partial"
	}
	if coverage.CorrelatedTaskCount == coverage.CandidateTaskCount {
		return "correlated"
	}
	if coverage.CorrelatedTaskCount > 0 {
		return "partial"
	}
	return "unknown"
}

func repositoryIdentityFromWorkingDirectory(raw string) providerRepositoryIdentity {
	workspace := cleanRepositoryPath(raw)
	if workspace == "" {
		return providerRepositoryIdentity{}
	}
	if info, err := os.Stat(workspace); err == nil && !info.IsDir() {
		workspace = filepath.Dir(workspace)
	}
	for current := workspace; current != ""; current = filepath.Dir(current) {
		marker := filepath.Join(current, ".git")
		if info, err := os.Stat(marker); err == nil {
			repositoryPath := current
			if !info.IsDir() {
				if canonical := canonicalRepositoryPathFromGitFile(marker); canonical != "" {
					repositoryPath = canonical
				}
			}
			return providerRepositoryIdentity{
				repositoryName: filepath.Base(repositoryPath),
				repositoryPath: repositoryPath,
				workspacePath:  current,
			}
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
	}
	return providerRepositoryIdentity{
		repositoryName: filepath.Base(workspace),
		repositoryPath: workspace,
		workspacePath:  workspace,
	}
}

func canonicalRepositoryPathFromGitFile(marker string) string {
	data, err := os.ReadFile(marker)
	if err != nil {
		return ""
	}
	line := strings.TrimSpace(string(data))
	if !strings.HasPrefix(strings.ToLower(line), "gitdir:") {
		return ""
	}
	gitDir := strings.TrimSpace(line[len("gitdir:"):])
	if !filepath.IsAbs(gitDir) {
		gitDir = filepath.Join(filepath.Dir(marker), gitDir)
	}
	gitDir = filepath.Clean(gitDir)
	commonDir := gitDir
	if value, readErr := os.ReadFile(filepath.Join(gitDir, "commondir")); readErr == nil {
		commonDir = strings.TrimSpace(string(value))
		if !filepath.IsAbs(commonDir) {
			commonDir = filepath.Join(gitDir, commonDir)
		}
		commonDir = filepath.Clean(commonDir)
	}
	if filepath.Base(commonDir) != ".git" {
		return ""
	}
	return cleanRepositoryPath(filepath.Dir(commonDir))
}

func cleanRepositoryPath(raw string) string {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return ""
	}
	if strings.HasPrefix(trimmed, "~"+string(filepath.Separator)) {
		if home, err := os.UserHomeDir(); err == nil {
			trimmed = filepath.Join(home, strings.TrimPrefix(trimmed, "~"+string(filepath.Separator)))
		}
	}
	cleaned := filepath.Clean(trimmed)
	if resolved, err := filepath.EvalSymlinks(cleaned); err == nil {
		cleaned = resolved
	}
	if absolute, err := filepath.Abs(cleaned); err == nil {
		cleaned = absolute
	}
	return filepath.Clean(cleaned)
}

func sameRepositoryPath(left, right string) bool {
	left = cleanRepositoryPath(left)
	right = cleanRepositoryPath(right)
	if left == "" || right == "" {
		return false
	}
	leftInfo, leftErr := os.Stat(left)
	rightInfo, rightErr := os.Stat(right)
	if leftErr == nil && rightErr == nil {
		return os.SameFile(leftInfo, rightInfo)
	}
	if runtime.GOOS == "windows" {
		return strings.EqualFold(left, right)
	}
	return left == right
}

func parseTokenUsageTime(raw string) time.Time {
	parsed, err := time.Parse("2006-01-02T15:04:05.000000000Z", raw)
	if err != nil {
		return time.Time{}
	}
	return parsed
}
