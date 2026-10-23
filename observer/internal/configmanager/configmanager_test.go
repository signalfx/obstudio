package configmanager

import (
	"strings"
	"testing"
)

func TestKeySpecValidate(t *testing.T) {
	tests := []struct {
		name    string
		spec    KeySpec
		wantErr string
	}{
		{"minimal", KeySpec{Key: "a.b", Type: TypeString}, ""},
		{"label and description", KeySpec{Key: "a.b", Type: TypeString, Label: "Realm", Description: "Where telemetry goes."}, ""},
		{"label at the limit", KeySpec{Key: "a", Type: TypeString, Label: strings.Repeat("x", MaxLabelLength)}, ""},
		{"label counts characters, not bytes", KeySpec{Key: "a", Type: TypeString, Label: strings.Repeat("é", MaxLabelLength)}, ""},
		{"description at the limit", KeySpec{Key: "a", Type: TypeString, Description: strings.Repeat("x", MaxDescriptionLength)}, ""},
		{"label too long", KeySpec{Key: "a", Type: TypeString, Label: strings.Repeat("x", MaxLabelLength+1)}, "label is 41 characters, the limit is 40"},
		{"description too long", KeySpec{Key: "a", Type: TypeString, Description: strings.Repeat("x", MaxDescriptionLength+1)}, "description is 121 characters, the limit is 120"},
		{"label with surrounding space", KeySpec{Key: "a", Type: TypeString, Label: " Realm"}, "leading or trailing whitespace"},
		{"description with trailing newline", KeySpec{Key: "a", Type: TypeString, Description: "Where.\n"}, "leading or trailing whitespace"},
		{"description with embedded newline", KeySpec{Key: "a", Type: TypeString, Description: "Where\ntelemetry goes."}, "single line"},
		{"label with tab", KeySpec{Key: "a", Type: TypeString, Label: "Re\talm"}, "single line"},
		{"no key", KeySpec{Type: TypeString}, "no key"},
		{"no type", KeySpec{Key: "a"}, "no type"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := test.spec.Validate()
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("Validate() = %v, want nil", err)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("Validate() = %v, want error containing %q", err, test.wantErr)
			}
		})
	}
}
