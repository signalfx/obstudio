package main

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"go.yaml.in/yaml/v3"
)

func TestFindTarget(t *testing.T) {
	t.Parallel()

	target, err := findTarget("darwin", "arm64")
	if err != nil {
		t.Fatalf("findTarget returned error: %v", err)
	}
	if target.asset != "weaver-aarch64-apple-darwin.tar.xz" {
		t.Fatalf("unexpected asset: %s", target.asset)
	}
	if target.bundledBinaryName != "weaver" {
		t.Fatalf("unexpected bundled binary name: %s", target.bundledBinaryName)
	}
}

func TestFindTargetUnsupported(t *testing.T) {
	t.Parallel()

	_, err := findTarget("linux", "arm64")
	if err == nil {
		t.Fatal("expected unsupported target error")
	}
}

func TestFetchAllWritesPerTargetDirectories(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	want := filepath.Join(dir, "darwin-arm64")
	if got := filepath.Join(dir, supportedTargets[0].goos+"-"+supportedTargets[0].goarch); got != want {
		t.Fatalf("unexpected release output layout: %s", got)
	}
}

func TestCopyFileWrapsSourcePathErrors(t *testing.T) {
	t.Parallel()

	src := filepath.Join(t.TempDir(), "missing")
	dst := filepath.Join(t.TempDir(), "out")

	err := copyFile(src, dst)
	if err == nil {
		t.Fatal("expected copyFile to fail for missing source")
	}
	if !strings.Contains(err.Error(), "open") || !strings.Contains(err.Error(), src) {
		t.Fatalf("expected wrapped source error, got %v", err)
	}
}

func TestCopyFileCopiesContents(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	src := filepath.Join(dir, "source.bin")
	dst := filepath.Join(dir, "dest.bin")
	if err := os.WriteFile(src, []byte("weaver"), 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}

	if err := copyFile(src, dst); err != nil {
		t.Fatalf("copyFile returned error: %v", err)
	}

	data, err := os.ReadFile(dst)
	if err != nil {
		t.Fatalf("read dest: %v", err)
	}
	if string(data) != "weaver" {
		t.Fatalf("unexpected destination contents: %q", string(data))
	}
}

func TestFetchTargetUsesCachedBinaryFromOverride(t *testing.T) {
	cacheRoot := t.TempDir()
	outputDir := t.TempDir()
	t.Setenv("OBSTUDIO_WEAVER_CACHE_DIR", cacheRoot)

	target, err := findTarget("darwin", "arm64")
	if err != nil {
		t.Fatalf("findTarget returned error: %v", err)
	}

	cacheBinary := filepath.Join(cacheRoot, weaverVersion, target.goos+"-"+target.goarch, target.bundledBinaryName)
	if err := os.MkdirAll(filepath.Dir(cacheBinary), 0o755); err != nil {
		t.Fatalf("create cache dir: %v", err)
	}
	if err := os.WriteFile(cacheBinary, []byte("cached-weaver"), 0o755); err != nil {
		t.Fatalf("write cached binary: %v", err)
	}

	if err := fetchTarget(t.Context(), outputDir, target.goos, target.goarch); err != nil {
		t.Fatalf("fetchTarget returned error: %v", err)
	}

	outputBinary := filepath.Join(outputDir, target.bundledBinaryName)
	data, err := os.ReadFile(outputBinary)
	if err != nil {
		t.Fatalf("read output binary: %v", err)
	}
	if string(data) != "cached-weaver" {
		t.Fatalf("unexpected output contents: %q", string(data))
	}
}

func TestReleaseMatrixMatchesWeaverSupportedTargets(t *testing.T) {
	t.Parallel()

	type ignoreTarget struct {
		Goos   string `yaml:"goos"`
		Goarch string `yaml:"goarch"`
	}
	type buildConfig struct {
		Goos   []string       `yaml:"goos"`
		Goarch []string       `yaml:"goarch"`
		Ignore []ignoreTarget `yaml:"ignore"`
	}
	type goreleaserConfig struct {
		Builds []buildConfig `yaml:"builds"`
	}

	configPath := filepath.Join("..", "..", "..", ".goreleaser.yaml")
	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read goreleaser config: %v", err)
	}

	var config goreleaserConfig
	if err := yaml.Unmarshal(data, &config); err != nil {
		t.Fatalf("unmarshal goreleaser config: %v", err)
	}

	published := map[string]struct{}{}
	for _, build := range config.Builds {
		ignored := map[string]struct{}{}
		for _, target := range build.Ignore {
			ignored[target.Goos+"/"+target.Goarch] = struct{}{}
		}
		for _, goos := range build.Goos {
			for _, goarch := range build.Goarch {
				key := goos + "/" + goarch
				if _, skip := ignored[key]; skip {
					continue
				}
				published[key] = struct{}{}
			}
		}
	}

	supported := make([]string, 0, len(supportedTargets))
	for _, target := range supportedTargets {
		supported = append(supported, target.goos+"/"+target.goarch)
	}
	slices.Sort(supported)

	publishedKeys := make([]string, 0, len(published))
	for key := range published {
		publishedKeys = append(publishedKeys, key)
	}
	slices.Sort(publishedKeys)

	if !reflect.DeepEqual(publishedKeys, supported) {
		t.Fatalf("release matrix %v does not match Weaver-supported targets %v", publishedKeys, supported)
	}
}
