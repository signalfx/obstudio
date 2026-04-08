package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/signalfx/obstudio/observer-go/internal/buildutil"
)

func main() {
	_, thisFile, _, _ := runtime.Caller(0)
	observerGoRoot := filepath.Dir(filepath.Dir(filepath.Dir(thisFile)))
	repoRoot := filepath.Dir(observerGoRoot)

	if err := buildutil.StageEmbeddedSkills(repoRoot, observerGoRoot); err != nil {
		fmt.Fprintf(os.Stderr, "stage embedded skills: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Staged embedded skills into %s\n", filepath.Join(observerGoRoot, "cmd", "obstudio", "_skills"))
}
