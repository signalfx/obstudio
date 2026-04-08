// build-client bundles the React UI using esbuild's Go API.
// This eliminates the need for a Node.js-based esbuild at build time.
// npm is still required to install React dependencies (react, react-dom, etc.)
// but is auto-invoked only when node_modules is missing.
//
// Usage: go run ./cmd/build-client
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	"github.com/evanw/esbuild/pkg/api"
)

func main() {
	// Resolve paths relative to this file's location.
	_, thisFile, _, _ := runtime.Caller(0)
	goRoot := filepath.Dir(filepath.Dir(filepath.Dir(thisFile)))           // observer-go/
	clientRoot := filepath.Join(goRoot, "client")                          // observer-go/client/
	outdir := filepath.Join(goRoot, "internal", "web", "static", "assets") // observer-go/internal/web/static/assets/

	// Verify the client source exists.
	entry := filepath.Join(clientRoot, "src", "main.tsx")
	if _, err := os.Stat(entry); err != nil {
		fmt.Fprintf(os.Stderr, "Client entry point not found: %s\n", entry)
		os.Exit(1)
	}

	// Install React dependencies if node_modules is missing.
	if !haveClientDependencies(clientRoot) {
		fmt.Println("Installing client dependencies...")
		installArgs := []string{"install", "--ignore-scripts"}
		if _, err := os.Stat(filepath.Join(clientRoot, "package-lock.json")); err == nil {
			installArgs = []string{"ci", "--ignore-scripts"}
		}
		cmd := exec.Command("npm", installArgs...)
		cmd.Dir = clientRoot
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "npm install failed: %v\n", err)
			os.Exit(1)
		}
	}

	result := api.Build(api.BuildOptions{
		AbsWorkingDir: clientRoot,
		EntryPoints:   []string{"src/main.tsx"},
		Bundle:        true,
		Outdir:        outdir,
		Format:        api.FormatIIFE,
		Platform:      api.PlatformBrowser,
		Target:        api.ES2022,
		JSX:           api.JSXAutomatic,
		Sourcemap:     api.SourceMapLinked,
		Loader: map[string]api.Loader{
			".css": api.LoaderCSS,
		},
		Write:    true,
		LogLevel: api.LogLevelInfo,
	})

	if len(result.Errors) > 0 {
		fmt.Fprintf(os.Stderr, "Build failed with %d errors\n", len(result.Errors))
		os.Exit(1)
	}

	fmt.Printf("Built client assets to %s\n", outdir)
}

func haveClientDependencies(clientRoot string) bool {
	requiredPaths := []string{
		filepath.Join(clientRoot, "node_modules", "react"),
		filepath.Join(clientRoot, "node_modules", "react-dom"),
		filepath.Join(clientRoot, "node_modules", "@tanstack", "react-virtual"),
	}

	for _, path := range requiredPaths {
		if _, err := os.Stat(path); err != nil {
			return false
		}
	}

	return true
}
