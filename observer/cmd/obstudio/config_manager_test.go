package main

import (
	"context"
	"testing"
)

func TestSampleConfigManagerSchemaIsWellFormedAndDescribed(t *testing.T) {
	specs, err := newConfigManager().Schema(context.Background())
	if err != nil {
		t.Fatalf("Schema: %v", err)
	}
	if len(specs) == 0 {
		t.Fatal("Schema returned no keys")
	}
	for _, spec := range specs {
		if err := spec.Validate(); err != nil {
			t.Errorf("%s: %v", spec.Key, err)
		}
		if spec.Label == "" || spec.Description == "" {
			t.Errorf("%s: sample config should demonstrate both a label and a description, got label=%q description=%q",
				spec.Key, spec.Label, spec.Description)
		}
	}
}
