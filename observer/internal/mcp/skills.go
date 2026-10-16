package mcp

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"mime"
	"path"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"
)

var validSkillName = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

var projectedSharedRoot = regexp.MustCompile(`Path\(__file__\)\.resolve\(\)\.parents\[2\](\s*)/ "references"`)

var errSkillsCapability = errors.New("Client must declare the Skills extension")

const skillsExtension = "io.modelcontextprotocol/skills"
const modernProtocol = "2026-07-28"
const maxSkillBytes = 16 * 1024 * 1024
const maxSkillFiles = 512

type skillResource struct {
	URI    string `json:"uri"`
	Digest string `json:"digest"`
	Size   int    `json:"size"`
}
type skillEntry struct {
	URI         string          `json:"uri"`
	Frontmatter map[string]any  `json:"frontmatter"`
	Resources   []skillResource `json:"resources"`
}
type servedSkill struct {
	entry skillEntry
	files map[string][]byte
}

// SkillCatalog holds a self-contained, immutable projection of embedded skills.
type SkillCatalog struct {
	skills      map[string]servedSkill
	names       []string
	unavailable []string
}

func NewSkillCatalog(source fs.FS) *SkillCatalog {
	catalog := &SkillCatalog{skills: make(map[string]servedSkill)}
	entries, err := fs.ReadDir(source, ".")
	if err != nil {
		return catalog
	}
	for _, entry := range entries {
		if !entry.IsDir() || entry.Name() == "references" {
			continue
		}
		name := entry.Name()
		if _, err := fs.Stat(source, name+"/SKILL.md"); err != nil {
			continue
		}
		skill, err := projectSkill(source, name)
		if err != nil {
			catalog.unavailable = append(catalog.unavailable, name)
			continue
		}
		catalog.skills[name] = skill
		catalog.names = append(catalog.names, name)
	}
	sort.Strings(catalog.names)
	return catalog
}

func projectSkill(source fs.FS, name string) (servedSkill, error) {
	skill := servedSkill{files: make(map[string][]byte)}
	if len(name) > 64 || !validSkillName.MatchString(name) {
		return skill, fmt.Errorf("invalid skill name")
	}
	total := 0
	addTree := func(root, prefix string, optional bool) error {
		siblings, err := fs.ReadDir(source, path.Dir(root))
		if err != nil {
			return err
		}
		for _, entry := range siblings {
			if entry.Name() == path.Base(root) && entry.Type()&fs.ModeSymlink != 0 {
				return fmt.Errorf("skill tree symlinks are not served")
			}
		}
		if _, err := fs.Stat(source, root); err != nil {
			if optional && errors.Is(err, fs.ErrNotExist) {
				return nil
			}
			return err
		}
		return fs.WalkDir(source, root, func(filename string, entry fs.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if entry.IsDir() {
				if entry.Name() == "tests" || entry.Name() == "__pycache__" || entry.Name() == "evals" {
					return fs.SkipDir
				}
				return nil
			}
			if entry.Type()&fs.ModeSymlink != 0 {
				return fmt.Errorf("skill symlinks are not served")
			}
			info, err := entry.Info()
			if err != nil {
				return err
			}
			if !info.Mode().IsRegular() || info.Size() > maxSkillBytes {
				return fmt.Errorf("invalid skill resource")
			}
			data, err := fs.ReadFile(source, filename)
			if err != nil {
				return err
			}
			// Keep shared source canonical while making every remote skill self-contained.
			if utf8.Valid(data) && path.Ext(filename) == ".md" {
				text := string(data)
				if path.Base(filename) == "SKILL.md" {
					_, body, err := parseSkillFrontmatter(data)
					if err != nil {
						return err
					}
					text = string(data[:body]) + strings.ReplaceAll(string(data[body:]), "../references/", "references/shared/")
				} else {
					text = strings.ReplaceAll(text, "../references/", "references/shared/")
				}
				data = []byte(text)
			}
			if utf8.Valid(data) && path.Ext(filename) == ".py" {
				data = projectedSharedRoot.ReplaceAll(data, []byte(`Path(__file__).resolve().parents[1]${1}/ "references" / "shared"`))
			}
			relative := strings.TrimPrefix(filename, root+"/")
			target := path.Join(prefix, relative)
			if _, exists := skill.files[target]; exists {
				return fmt.Errorf("colliding skill resource")
			}
			total += len(data)
			if total > maxSkillBytes || len(skill.files) >= maxSkillFiles {
				return fmt.Errorf("skill resource limit")
			}
			skill.files[target] = data
			return nil
		})
	}
	if err := addTree(name, "", false); err != nil {
		return skill, err
	}
	if err := addTree("references", "references/shared", true); err != nil {
		return skill, err
	}
	data := skill.files["SKILL.md"]
	frontmatter, _, err := parseSkillFrontmatter(data)
	if err != nil {
		return skill, err
	}
	if _, err := json.Marshal(frontmatter); err != nil {
		return skill, fmt.Errorf("frontmatter is not JSON-compatible")
	}
	skill.entry.Frontmatter = frontmatter
	if skill.entry.Frontmatter["name"] != name {
		return skill, fmt.Errorf("skill name mismatch")
	}
	if value, ok := skill.entry.Frontmatter["description"].(string); !ok || strings.TrimSpace(value) == "" {
		return skill, fmt.Errorf("missing description")
	}
	skill.entry.URI = skillURI(name, "SKILL.md")
	paths := make([]string, 0, len(skill.files))
	for filename := range skill.files {
		paths = append(paths, filename)
	}
	sort.Strings(paths)
	for _, filename := range paths {
		data := skill.files[filename]
		skill.entry.Resources = append(skill.entry.Resources, skillResource{
			URI: skillURI(name, filename), Digest: fmt.Sprintf("sha256:%x", sha256.Sum256(data)), Size: len(data),
		})
	}
	return skill, nil
}

func skillURI(name, filename string) string { return "skill://obstudio/" + name + "/" + filename }

func (c *SkillCatalog) resolve(uri string) (string, string, bool) {
	if c == nil {
		return "", "", false
	}
	for _, name := range c.names {
		prefix := "skill://obstudio/" + name + "/"
		if strings.HasPrefix(uri, prefix) {
			filename := strings.TrimPrefix(uri, prefix)
			if !fs.ValidPath(filename) || strings.ContainsAny(filename, "%\\?#") {
				return "", "", false
			}
			return name, filename, true
		}
	}
	return "", "", false
}

func (c *SkillCatalog) read(uri string) (map[string]any, error) {
	name, filename, ok := c.resolve(uri)
	if !ok {
		return nil, fmt.Errorf("unknown skill resource")
	}
	data, ok := c.skills[name].files[filename]
	if !ok {
		return nil, fmt.Errorf("unknown skill resource")
	}
	resource := map[string]any{"uri": uri}
	mimeType := mime.TypeByExtension(path.Ext(filename))
	if utf8.Valid(data) {
		if mimeType == "" {
			mimeType = "text/plain"
		}
		resource["text"] = string(data)
	} else {
		if mimeType == "" {
			mimeType = "application/octet-stream"
		}
		resource["blob"] = base64.StdEncoding.EncodeToString(data)
	}
	if filename == "SKILL.md" {
		mimeType = "text/markdown"
	}
	resource["mimeType"] = mimeType
	return resource, nil
}

func (d *Dispatcher) skillRequest(req jsonRPCRequest) jsonRPCResponse {
	params, _ := toMap(req.Params)
	if req.Method != "resources/read" && req.Method != "resources/list" {
		if err := validateSkillMetadata(params, req.Method != "server/discover"); err != nil {
			if errors.Is(err, errSkillsCapability) {
				response := rpcError(req.ID, -32021, err.Error())
				response.Error.Data = map[string]any{"requiredCapabilities": map[string]any{"extensions": map[string]any{skillsExtension: map[string]any{}}}}
				return response
			}
			return rpcError(req.ID, -32602, err.Error())
		}
	}
	if req.Method != "server/discover" && (d.skillCatalog == nil || len(d.skillCatalog.names) == 0) {
		return rpcError(req.ID, -32601, "Skills catalog unavailable")
	}
	switch req.Method {
	case "server/discover":
		capabilities := map[string]any{"tools": map[string]any{}}
		if d.skillCatalog != nil && len(d.skillCatalog.names) > 0 {
			capabilities["resources"] = map[string]any{}
			capabilities["extensions"] = map[string]any{skillsExtension: map[string]any{"directoryRead": true}}
		}
		return rpcResult(req.ID, cacheResult(map[string]any{
			"supportedVersions": append([]string{modernProtocol}, supportedVersions...),
			"capabilities":      capabilities,
			"_meta":             map[string]any{"io.modelcontextprotocol/serverInfo": map[string]any{"name": "obstudio", "version": "dev"}},
		}))
	case "skills/list":
		if strArg(params, "cursor") != "" {
			return rpcError(req.ID, -32602, "Invalid cursor")
		}
		entries := make([]skillEntry, 0, len(d.skillCatalog.names))
		for _, name := range d.skillCatalog.names {
			entries = append(entries, d.skillCatalog.skills[name].entry)
		}
		return rpcResult(req.ID, cacheResult(map[string]any{"skills": entries}))
	case "skills/get":
		name, filename, ok := d.skillCatalog.resolve(strArg(params, "uri"))
		if !ok || filename != "SKILL.md" {
			return rpcError(req.ID, -32602, "Unknown skill")
		}
		return rpcResult(req.ID, cacheResult(map[string]any{"skill": d.skillCatalog.skills[name].entry}))
	case "resources/list":
		resources := []map[string]any{}
		for _, name := range d.skillCatalog.names {
			entry := d.skillCatalog.skills[name].entry
			resources = append(resources, map[string]any{"uri": entry.URI, "name": name, "description": entry.Frontmatter["description"], "mimeType": "text/markdown"})
		}
		return rpcResult(req.ID, cacheResult(map[string]any{"resources": resources}))
	case "resources/read":
		started := timeNow()
		uri := strArg(params, "uri")
		resource, err := d.skillCatalog.read(uri)
		d.recordSkillRead(uri, started, err == nil)
		if err != nil {
			return rpcError(req.ID, -32602, err.Error())
		}
		return rpcResult(req.ID, cacheResult(map[string]any{"contents": []map[string]any{resource}}))
	case "resources/directory/read":
		if strArg(params, "cursor") != "" {
			return rpcError(req.ID, -32602, "Invalid cursor")
		}
		uri := strArg(params, "uri")
		name, directory, ok := d.skillCatalog.resolve(uri + "/placeholder")
		if !ok || strings.HasSuffix(uri, "/") {
			return rpcError(req.ID, -32602, "Unknown skill directory")
		}
		directory = strings.TrimSuffix(directory, "placeholder")
		children := map[string]bool{}
		for filename := range d.skillCatalog.skills[name].files {
			if strings.HasPrefix(filename, directory) {
				rest := strings.TrimPrefix(filename, directory)
				pieces := strings.SplitN(rest, "/", 2)
				children[pieces[0]] = len(pieces) == 2
			}
		}
		if len(children) == 0 {
			return rpcError(req.ID, -32602, "Unknown skill directory")
		}
		names := make([]string, 0, len(children))
		for child := range children {
			names = append(names, child)
		}
		sort.Strings(names)
		resources := []map[string]any{}
		for _, child := range names {
			mimeType := mime.TypeByExtension(path.Ext(child))
			if children[child] {
				mimeType = "inode/directory"
			}
			if mimeType == "" {
				mimeType = "text/plain"
			}
			resources = append(resources, map[string]any{"uri": uri + "/" + child, "name": child, "mimeType": mimeType})
		}
		return rpcResult(req.ID, cacheResult(map[string]any{"resources": resources}))
	}
	return rpcError(req.ID, -32601, "Unknown method")
}

func validateSkillMetadata(params map[string]any, requireExtension bool) error {
	meta, _ := toMap(params["_meta"])
	if strArg(meta, "io.modelcontextprotocol/protocolVersion") != modernProtocol {
		return fmt.Errorf("Skills require protocol " + modernProtocol)
	}
	caps, ok := toMap(meta["io.modelcontextprotocol/clientCapabilities"])
	if !ok {
		return fmt.Errorf("Missing required client capabilities")
	}
	if value, present := meta["io.modelcontextprotocol/clientInfo"]; present {
		info, valid := toMap(value)
		if !valid || strArg(info, "name") == "" || strArg(info, "version") == "" {
			return fmt.Errorf("Invalid optional client identity")
		}
	}
	extensions, _ := toMap(caps["extensions"])
	if requireExtension {
		if _, ok := toMap(extensions[skillsExtension]); !ok {
			return errSkillsCapability
		}
	}
	return nil
}

func cacheResult(result map[string]any) map[string]any {
	result["resultType"] = "complete"
	result["ttlMs"] = 0
	result["cacheScope"] = "private"
	return result
}

func parseSkillFrontmatter(data []byte) (map[string]any, int, error) {
	if !utf8.Valid(data) {
		return nil, 0, fmt.Errorf("invalid skill encoding")
	}
	lines := strings.SplitAfter(string(data), "\n")
	if len(lines) == 0 || strings.TrimRight(lines[0], "\r\n") != "---" {
		return nil, 0, fmt.Errorf("missing frontmatter")
	}
	offset := len(lines[0])
	for _, line := range lines[1:] {
		if strings.TrimRight(line, "\r\n") == "---" {
			var metadata map[string]any
			if err := yaml.Unmarshal(data[len(lines[0]):offset], &metadata); err != nil {
				return nil, 0, err
			}
			return metadata, offset + len(line), nil
		}
		offset += len(line)
	}
	return nil, 0, fmt.Errorf("unterminated frontmatter")
}
