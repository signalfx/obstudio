package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"github.com/signalfx/obstudio/observer/internal/buildutil"
)

func main() {
	_, thisFile, _, _ := runtime.Caller(0)
	observerRoot := filepath.Dir(filepath.Dir(filepath.Dir(thisFile)))
	repoRoot := filepath.Dir(observerRoot)

	if err := buildutil.StageEmbeddedSkills(repoRoot, observerRoot); err != nil {
		fmt.Fprintf(os.Stderr, "stage embedded skills: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Staged embedded skills into %s\n", filepath.Join(observerRoot, "cmd", "obstudio", "_skills"))
}
