package web

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStaticIndexReferencesObserverIcon(t *testing.T) {
	rootDir := filepath.Join("static")
	indexBytes, err := os.ReadFile(filepath.Join(rootDir, "index.html"))
	if err != nil {
		t.Fatalf("read static index: %v", err)
	}

	if !strings.Contains(string(indexBytes), `/assets/observer-icon.svg`) {
		t.Fatal("static index should reference the observer favicon asset")
	}

	if _, err := os.Stat(filepath.Join(rootDir, "assets", "observer-icon.svg")); err != nil {
		t.Fatalf("observer favicon asset missing: %v", err)
	}
}
