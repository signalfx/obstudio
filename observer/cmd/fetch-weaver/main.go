package main

import (
	"archive/tar"
	"archive/zip"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/ulikunitz/xz"
)

const (
	weaverVersion         = "v0.22.1"
	downloadBase          = "https://github.com/open-telemetry/weaver/releases/download/" + weaverVersion
	downloadRetryDelay    = 500 * time.Millisecond
	downloadRetryAttempts = 4
)

type target struct {
	goos              string
	goarch            string
	asset             string
	archiveBinaryName string
	bundledBinaryName string
}

var supportedTargets = []target{
	{goos: "darwin", goarch: "arm64", asset: "weaver-aarch64-apple-darwin.tar.xz", archiveBinaryName: "weaver", bundledBinaryName: "weaver"},
	{goos: "darwin", goarch: "amd64", asset: "weaver-x86_64-apple-darwin.tar.xz", archiveBinaryName: "weaver", bundledBinaryName: "weaver"},
	{goos: "linux", goarch: "amd64", asset: "weaver-x86_64-unknown-linux-gnu.tar.xz", archiveBinaryName: "weaver", bundledBinaryName: "weaver"},
	{goos: "windows", goarch: "amd64", asset: "weaver-x86_64-pc-windows-msvc.zip", archiveBinaryName: "weaver.exe", bundledBinaryName: "weaver.exe"},
}

func main() {
	var (
		allTargets bool
		goos       string
		goarch     string
		outputDir  string
	)

	flag.BoolVar(&allTargets, "all", false, "fetch Weaver for all supported release targets")
	flag.StringVar(&goos, "goos", runtime.GOOS, "target operating system")
	flag.StringVar(&goarch, "goarch", runtime.GOARCH, "target architecture")
	flag.StringVar(&outputDir, "output", "", "destination directory")
	flag.Parse()

	if outputDir == "" {
		log.Fatal("missing required -output flag")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	var err error
	if allTargets {
		err = fetchAll(ctx, outputDir)
	} else {
		err = fetchTarget(ctx, outputDir, goos, goarch)
	}
	if err != nil {
		log.Fatal(err)
	}
}

func fetchAll(ctx context.Context, root string) error {
	for _, target := range supportedTargets {
		destDir := filepath.Join(root, target.goos+"-"+target.goarch)
		if err := fetchTarget(ctx, destDir, target.goos, target.goarch); err != nil {
			return err
		}
	}
	return nil
}

func fetchTarget(ctx context.Context, outputDir, goos, goarch string) error {
	target, err := findTarget(goos, goarch)
	if err != nil {
		return err
	}

	cachedBinary, err := ensureCachedBinary(ctx, target)
	if err != nil {
		return err
	}

	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return fmt.Errorf("create output dir: %w", err)
	}

	outputBinary := filepath.Join(outputDir, target.bundledBinaryName)
	if err := copyFile(cachedBinary, outputBinary); err != nil {
		return fmt.Errorf("copy weaver binary: %w", err)
	}
	if err := makeExecutable(outputBinary); err != nil {
		return fmt.Errorf("chmod weaver binary: %w", err)
	}
	return nil
}

func findTarget(goos, goarch string) (target, error) {
	for _, target := range supportedTargets {
		if target.goos == goos && target.goarch == goarch {
			return target, nil
		}
	}
	return target{}, fmt.Errorf("unsupported Weaver target %s/%s (supported: %s)", goos, goarch, strings.Join(supportedTargetNames(), ", "))
}

func supportedTargetNames() []string {
	names := make([]string, 0, len(supportedTargets))
	for _, target := range supportedTargets {
		names = append(names, target.goos+"/"+target.goarch)
	}
	sort.Strings(names)
	return names
}

func ensureCachedBinary(ctx context.Context, target target) (string, error) {
	cacheRoot, err := weaverCacheDir()
	if err != nil {
		return "", err
	}
	cacheDir := filepath.Join(cacheRoot, target.goos+"-"+target.goarch)
	cachedBinary := filepath.Join(cacheDir, target.bundledBinaryName)
	if _, err := os.Stat(cachedBinary); err == nil {
		return cachedBinary, nil
	}

	tmpDir, err := os.MkdirTemp("", "obstudio-weaver-*")
	if err != nil {
		return "", fmt.Errorf("create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	archivePath := filepath.Join(tmpDir, target.asset)
	if err := downloadFile(ctx, downloadBase+"/"+target.asset, archivePath); err != nil {
		return "", err
	}
	extractedBinary, err := extractBinary(archivePath, tmpDir, target.archiveBinaryName)
	if err != nil {
		return "", err
	}

	if err := os.MkdirAll(cacheDir, 0o755); err != nil {
		return "", fmt.Errorf("create cache dir: %w", err)
	}
	cacheTmp := cachedBinary + ".tmp"
	if err := copyFile(extractedBinary, cacheTmp); err != nil {
		return "", fmt.Errorf("write cache binary: %w", err)
	}
	if err := makeExecutable(cacheTmp); err != nil {
		return "", fmt.Errorf("chmod cache binary: %w", err)
	}
	if err := os.Rename(cacheTmp, cachedBinary); err != nil {
		return "", fmt.Errorf("finalize cache binary: %w", err)
	}
	return cachedBinary, nil
}

func weaverCacheDir() (string, error) {
	if override := os.Getenv("OBSTUDIO_WEAVER_CACHE_DIR"); override != "" {
		return filepath.Join(override, weaverVersion), nil
	}
	cacheRoot, err := os.UserCacheDir()
	if err != nil {
		return "", fmt.Errorf("resolve user cache dir: %w", err)
	}
	return filepath.Join(cacheRoot, "obstudio", "weaver", weaverVersion), nil
}

func downloadFile(ctx context.Context, url, destination string) error {
	return downloadFileWithClient(ctx, http.DefaultClient, url, destination, downloadRetryAttempts, downloadRetryDelay)
}

type httpClient interface {
	Do(*http.Request) (*http.Response, error)
}

func downloadFileWithClient(ctx context.Context, client httpClient, url, destination string, attempts int, retryDelay time.Duration) error {
	if attempts < 1 {
		attempts = 1
	}

	var lastErr error
	for attempt := 1; attempt <= attempts; attempt++ {
		err, retryable := downloadFileOnce(ctx, client, url, destination)
		if err == nil {
			return nil
		}
		lastErr = err
		if !retryable || attempt == attempts {
			return err
		}

		wait := retryDelay * time.Duration(attempt)
		log.Printf("download %s failed on attempt %d/%d: %v; retrying in %s", url, attempt, attempts, err, wait)
		if wait <= 0 {
			continue
		}
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return fmt.Errorf("download %s: %w", url, ctx.Err())
		case <-timer.C:
		}
	}
	return lastErr
}

func downloadFileOnce(ctx context.Context, client httpClient, url, destination string) (error, bool) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return fmt.Errorf("create download request: %w", err), false
	}
	req.Header.Set("User-Agent", "obstudio-fetch-weaver/"+weaverVersion)

	resp, err := client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return fmt.Errorf("download %s: %w", url, ctx.Err()), false
		}
		return fmt.Errorf("download %s: %w", url, err), true
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		err := fmt.Errorf("download %s: unexpected status %s", url, resp.Status)
		return err, isRetryableDownloadStatus(resp.StatusCode)
	}

	out, err := os.Create(destination)
	if err != nil {
		return fmt.Errorf("create archive file: %w", err), false
	}
	defer out.Close()

	if _, err := io.Copy(out, resp.Body); err != nil {
		return fmt.Errorf("write archive file: %w", err), true
	}
	return nil, false
}

func isRetryableDownloadStatus(statusCode int) bool {
	return statusCode == http.StatusRequestTimeout ||
		statusCode == http.StatusTooManyRequests ||
		statusCode >= http.StatusInternalServerError
}

func extractBinary(archivePath, workDir, binaryName string) (string, error) {
	if strings.HasSuffix(archivePath, ".zip") {
		return extractZipBinary(archivePath, workDir, binaryName)
	}
	if strings.HasSuffix(archivePath, ".tar.xz") {
		return extractTarXZBinary(archivePath, workDir, binaryName)
	}
	return "", fmt.Errorf("unsupported archive format: %s", archivePath)
}

func extractZipBinary(archivePath, workDir, binaryName string) (string, error) {
	reader, err := zip.OpenReader(archivePath)
	if err != nil {
		return "", fmt.Errorf("open zip archive: %w", err)
	}
	defer reader.Close()

	for _, file := range reader.File {
		if filepath.Base(file.Name) != binaryName {
			continue
		}

		rc, err := file.Open()
		if err != nil {
			return "", fmt.Errorf("open zip entry: %w", err)
		}
		defer rc.Close()

		destPath := filepath.Join(workDir, binaryName)
		if err := writeReader(destPath, rc); err != nil {
			return "", err
		}
		return destPath, nil
	}
	return "", fmt.Errorf("binary %s not found in %s", binaryName, archivePath)
}

func extractTarXZBinary(archivePath, workDir, binaryName string) (string, error) {
	file, err := os.Open(archivePath)
	if err != nil {
		return "", fmt.Errorf("open tar.xz archive: %w", err)
	}
	defer file.Close()

	xzReader, err := xz.NewReader(file)
	if err != nil {
		return "", fmt.Errorf("open xz stream: %w", err)
	}
	tarReader := tar.NewReader(xzReader)

	for {
		header, err := tarReader.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return "", fmt.Errorf("read tar entry: %w", err)
		}
		if header.Typeflag != tar.TypeReg || filepath.Base(header.Name) != binaryName {
			continue
		}

		destPath := filepath.Join(workDir, binaryName)
		if err := writeReader(destPath, tarReader); err != nil {
			return "", err
		}
		return destPath, nil
	}
	return "", fmt.Errorf("binary %s not found in %s", binaryName, archivePath)
}

func writeReader(destination string, src io.Reader) error {
	out, err := os.Create(destination)
	if err != nil {
		return fmt.Errorf("create extracted binary: %w", err)
	}
	defer out.Close()

	if _, err := io.Copy(out, src); err != nil {
		return fmt.Errorf("extract binary: %w", err)
	}
	return nil
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("open %q: %w", src, err)
	}
	defer in.Close()

	out, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("create %q: %w", dst, err)
	}

	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return fmt.Errorf("copy %q to %q: %w", src, dst, err)
	}
	if err := out.Close(); err != nil {
		return fmt.Errorf("close %q: %w", dst, err)
	}
	return nil
}

func makeExecutable(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	return os.Chmod(path, 0o755)
}
