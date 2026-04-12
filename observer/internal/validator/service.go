package validator

import (
	"context"
	"errors"
	"fmt"
	"time"
)

type Runner interface {
	Run(context.Context) Summary
}

type FreshnessMode string

const (
	FreshnessAuto          FreshnessMode = "auto"
	FreshnessFreshRequired FreshnessMode = "fresh_required"
	FreshnessLatestOK      FreshnessMode = "latest_ok"
)

type ServiceErrorKind string

const (
	ErrRunnerUnavailable ServiceErrorKind = "runner_unavailable"
	ErrNoRetainedResult  ServiceErrorKind = "no_retained_result"
	ErrRunStillRunning   ServiceErrorKind = "run_still_running"
	ErrRunNotRetained    ServiceErrorKind = "run_not_retained"
	ErrRunFailed         ServiceErrorKind = "run_failed"
	ErrRunTimeout        ServiceErrorKind = "run_timeout"
	ErrNoAnalysis        ServiceErrorKind = "no_analysis_available"
)

type ServiceError struct {
	Kind              ServiceErrorKind
	Summary           Summary
	RequestedRunID    string
	AvailableResultID string
	Cause             error
}

func (e *ServiceError) Error() string {
	if e == nil {
		return ""
	}
	if e.Cause != nil {
		return e.Cause.Error()
	}
	switch e.Kind {
	case ErrRunnerUnavailable:
		return "validation runner unavailable"
	case ErrNoRetainedResult:
		return "validation has not been run yet and no retained result is available"
	case ErrRunStillRunning:
		return fmt.Sprintf("validation run %q is still running", e.RequestedRunID)
	case ErrRunNotRetained:
		return fmt.Sprintf("validation results for run %q are not retained", e.RequestedRunID)
	case ErrRunFailed:
		return "validation run failed"
	case ErrRunTimeout:
		return "validation run did not complete before timeout"
	case ErrNoAnalysis:
		return "validation did not produce analysis"
	default:
		return "validation unavailable"
	}
}

func (e *ServiceError) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Cause
}

type Service struct {
	store  *Store
	runner Runner
}

func NewService(store *Store, runner Runner) *Service {
	if store == nil {
		store = NewStore()
	}
	return &Service{store: store, runner: runner}
}

func (s *Service) Summary() Summary {
	return s.store.Summary()
}

func (s *Service) Run(ctx context.Context) (Summary, error) {
	if s.runner == nil {
		return Summary{}, &ServiceError{
			Kind:    ErrRunnerUnavailable,
			Summary: s.store.Summary(),
		}
	}
	return s.runner.Run(ctx), nil
}

func (s *Service) Latest(q Query) (Snapshot, error) {
	summary := s.store.Summary()
	if !LatestAvailable(summary) {
		return Snapshot{}, &ServiceError{
			Kind:    ErrNoRetainedResult,
			Summary: summary,
		}
	}
	return Snapshot{
		Summary:  summary,
		Findings: s.store.QueryFindings(q),
		Issues:   s.store.QueryIssues(q),
	}, nil
}

func (s *Service) Findings(q Query, runID string) ([]Finding, error) {
	summary := s.store.Summary()
	if runID != "" {
		if err := validationRunAccessError(summary, runID); err != nil {
			return nil, err
		}
		return s.store.QueryFindings(q), nil
	}
	if !LatestAvailable(summary) {
		return nil, &ServiceError{
			Kind:    ErrNoRetainedResult,
			Summary: summary,
		}
	}
	return s.store.QueryFindings(q), nil
}

func (s *Service) Analyze(ctx context.Context, q Query, freshness FreshnessMode, timeout time.Duration) (Analysis, error) {
	summary := s.store.Summary()
	switch freshness {
	case FreshnessFreshRequired:
		return s.runAnalysis(ctx, q, timeout)
	case FreshnessLatestOK:
		if !LatestAvailable(summary) {
			return Analysis{}, &ServiceError{
				Kind:    ErrNoRetainedResult,
				Summary: summary,
			}
		}
	default:
		if !LatestAvailable(summary) {
			return s.runAnalysis(ctx, q, timeout)
		}
	}
	return AnalysisForSummary(s.store, summary, q, AnalysisBasisFromSummary(summary)), nil
}

func (s *Service) Refresh(ctx context.Context, q Query, timeout time.Duration) (Analysis, error) {
	return s.runAnalysis(ctx, q, timeout)
}

func (s *Service) runAnalysis(ctx context.Context, q Query, timeout time.Duration) (Analysis, error) {
	summary := s.store.Summary()
	if s.runner == nil {
		return Analysis{}, &ServiceError{
			Kind:    ErrRunnerUnavailable,
			Summary: summary,
		}
	}
	if !summary.Enabled {
		s.store.SetRuntimeStatus(StatusIdle, "Validation has not been run yet")
	}

	started := s.runner.Run(ctx)
	runID := started.ActiveRunID
	if runID == "" {
		if LatestAvailable(started) {
			return AnalysisForSummary(s.store, started, q, AnalysisBasisFreshRun), nil
		}
		return Analysis{}, &ServiceError{
			Kind:    ErrNoAnalysis,
			Summary: started,
		}
	}

	waitCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	snapshot, err := WaitForRun(waitCtx, s.store, runID, q)
	if err != nil {
		var serviceErr *ServiceError
		if errors.As(err, &serviceErr) {
			return Analysis{}, serviceErr
		}
		return Analysis{}, err
	}

	return Analysis{
		AnalysisBasis: AnalysisBasisFreshRun,
		Summary:       snapshot.Summary,
		Findings:      snapshot.Findings,
		Issues:        snapshot.Issues,
	}, nil
}

func WaitForRun(ctx context.Context, store *Store, runID string, q Query) (Snapshot, error) {
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()

	for {
		summary := store.Summary()
		if summary.ResultRunID == runID && summary.HasResult {
			return Snapshot{
				Summary:  summary,
				Findings: store.QueryFindings(q),
				Issues:   store.QueryIssues(q),
			}, nil
		}
		if summary.ActiveRunID != "" && summary.ActiveRunID != runID {
			return Snapshot{}, &ServiceError{
				Kind:    ErrRunNotRetained,
				Summary: summary,
				Cause:   fmt.Errorf("validation run %q completed, but a newer run %q replaced it before results were fetched", runID, summary.ActiveRunID),
			}
		}
		if summary.ActiveRunID == "" && summary.Status == StatusError {
			return Snapshot{}, &ServiceError{
				Kind:    ErrRunFailed,
				Summary: summary,
				Cause:   fmt.Errorf("validation run %q failed: %s", runID, summary.LastError),
			}
		}

		select {
		case <-ctx.Done():
			return Snapshot{}, &ServiceError{
				Kind:    ErrRunTimeout,
				Summary: store.Summary(),
				Cause:   fmt.Errorf("validation run %q did not complete before timeout", runID),
			}
		case <-ticker.C:
		}
	}
}

func Fresh(summary Summary) bool {
	return summary.Enabled && summary.Ready && summary.HasResult && !summary.Stale
}

func LatestAvailable(summary Summary) bool {
	return summary.HasResult
}

func AnalysisBasisFromSummary(summary Summary) AnalysisBasis {
	if summary.Stale {
		return AnalysisBasisStaleResult
	}
	return AnalysisBasisLatestFresh
}

func AnalysisMessage(summary Summary, basis AnalysisBasis) string {
	if basis != AnalysisBasisStaleResult {
		return ""
	}
	runID := summary.ResultRunID
	if runID == "" {
		runID = "latest retained run"
	}
	if summary.LastRunCompletedAt.IsZero() {
		return fmt.Sprintf("Validation analysis is based on %s. New telemetry has arrived since then.", runID)
	}
	return fmt.Sprintf(
		"Validation analysis is based on run %s completed at %s. New telemetry has arrived since then.",
		runID,
		summary.LastRunCompletedAt.UTC().Format(time.RFC3339),
	)
}

func AnalysisForSummary(store *Store, summary Summary, q Query, basis AnalysisBasis) Analysis {
	return Analysis{
		AnalysisBasis:   basis,
		AnalysisMessage: AnalysisMessage(summary, basis),
		Summary:         summary,
		Findings:        store.QueryFindings(q),
		Issues:          store.QueryIssues(q),
	}
}

func ReadError(summary Summary) string {
	switch {
	case !summary.Enabled:
		return "validator unavailable"
	case summary.Status == StatusRunning:
		return "validation is still running"
	case summary.Status == StatusError:
		return "latest validation attempt failed"
	case !summary.HasResult:
		return "validation has not been run yet"
	case summary.Stale:
		return "validation results are stale"
	default:
		return "validation results are unavailable"
	}
}

func LatestReadError(summary Summary) string {
	switch {
	case !summary.Enabled:
		return "validator unavailable"
	case summary.Status == StatusRunning:
		return "validation is still running and no previous result is retained yet"
	case summary.Status == StatusError:
		return "latest validation attempt failed and no previous result is retained"
	default:
		return "validation has not been run yet"
	}
}

func validationRunAccessError(summary Summary, runID string) error {
	switch {
	case runID == "":
		return nil
	case summary.ResultRunID == runID && summary.HasResult:
		return nil
	case summary.ActiveRunID == runID:
		return &ServiceError{
			Kind:           ErrRunStillRunning,
			Summary:        summary,
			RequestedRunID: runID,
		}
	case summary.ResultRunID == "":
		return &ServiceError{
			Kind:           ErrNoRetainedResult,
			Summary:        summary,
			RequestedRunID: runID,
		}
	default:
		return &ServiceError{
			Kind:              ErrRunNotRetained,
			Summary:           summary,
			RequestedRunID:    runID,
			AvailableResultID: summary.ResultRunID,
		}
	}
}
