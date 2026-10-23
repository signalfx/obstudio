package configmanagertest

import (
	"context"
	"errors"
	"sync"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/configmanager"
)

func TestMockSetUnknownKeyAndValidation(t *testing.T) {
	mock := New(map[string]any{"a.b": "one"}).WithValidator("a.b", func(value any) error {
		if value == "bad" {
			return errors.New("nope")
		}
		return nil
	})
	ctx := context.Background()

	if err := mock.Set(ctx, "a.c", "x"); !errors.Is(err, configmanager.ErrUnknownKey) {
		t.Errorf("Set unknown key err = %v, want ErrUnknownKey", err)
	}
	var validationErr *configmanager.ValidationError
	if err := mock.Set(ctx, "a.b", "bad"); !errors.As(err, &validationErr) || validationErr.Message != "nope" {
		t.Errorf("Set invalid value err = %v, want ValidationError(nope)", err)
	}
	if got, _ := mock.Get(ctx, "a.b"); got != "one" {
		t.Errorf("value after rejected Set = %v, want one", got)
	}
	if err := mock.Set(ctx, "a.b", "two"); err != nil {
		t.Fatalf("Set valid value: %v", err)
	}
	if got, _ := mock.Get(ctx, "a.b"); got != "two" {
		t.Errorf("value after Set = %v, want two", got)
	}
}

func TestMockGetReturnsSectionsAndIsolatesSnapshots(t *testing.T) {
	mock := New(map[string]any{"a.b": 1, "a.c": 2})
	ctx := context.Background()

	section, err := mock.Get(ctx, "a")
	if err != nil {
		t.Fatalf("Get section: %v", err)
	}
	section.(map[string]any)["b"] = 99
	if got, _ := mock.Get(ctx, "a.b"); got != 1 {
		t.Errorf("a.b = %v after mutating a returned snapshot, want 1", got)
	}
	if _, err := mock.Get(ctx, "a.b.c"); !errors.Is(err, configmanager.ErrUnknownKey) {
		t.Errorf("Get below a leaf err = %v, want ErrUnknownKey", err)
	}
}

func TestMockIsSafeForConcurrentUse(t *testing.T) {
	mock := New(map[string]any{"a.b": 0})
	ctx := context.Background()
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(2)
		go func(i int) { defer wg.Done(); _ = mock.Set(ctx, "a.b", i) }(i)
		go func() { defer wg.Done(); _, _ = mock.GetAll(ctx) }()
	}
	wg.Wait()
	if got := len(mock.SetCalls()); got != 20 {
		t.Errorf("Set calls = %d, want 20", got)
	}
}

func TestMockSetManyIsAllOrNothingAndReportsEveryRejection(t *testing.T) {
	mock := New(map[string]any{"a.b": 1, "a.c": 2}).WithValidator("a.c", func(value any) error {
		return errors.New("never valid")
	})
	ctx := context.Background()

	err := mock.SetMany(ctx, map[string]any{"a.b": 10, "a.c": 20, "a.missing": 30})
	var batch *configmanager.ValidationErrors
	if !errors.As(err, &batch) || len(batch.Errors) != 2 {
		t.Fatalf("SetMany err = %v, want ValidationErrors with 2 entries", err)
	}
	if batch.Errors[0].Key != "a.c" || batch.Errors[1].Key != "a.missing" {
		t.Errorf("rejected keys = %q, %q, want a.c then a.missing", batch.Errors[0].Key, batch.Errors[1].Key)
	}
	if got, _ := mock.Get(ctx, "a.b"); got != 1 {
		t.Errorf("a.b = %v after a rejected batch, want 1 (unchanged)", got)
	}

	if err := mock.SetMany(ctx, map[string]any{"a.b": 10}); err != nil {
		t.Fatalf("SetMany valid batch: %v", err)
	}
	if got, _ := mock.Get(ctx, "a.b"); got != 10 {
		t.Errorf("a.b = %v after a valid batch, want 10", got)
	}
}

func TestMockSchemaReportsSpecsAndInfersTypesForUndeclaredKeys(t *testing.T) {
	minimum := int64(1)
	mock := New(map[string]any{"b.flag": true, "a.name": "x", "a.count": float64(3), "a.limit": 5}).
		WithSpec(configmanager.KeySpec{Key: "a.limit", Type: configmanager.TypeInteger, Minimum: &minimum})

	specs, err := mock.Schema(context.Background())
	if err != nil {
		t.Fatalf("Schema: %v", err)
	}
	var got []string
	for _, spec := range specs {
		got = append(got, spec.Key+":"+string(spec.Type))
	}
	want := []string{"a.count:integer", "a.limit:integer", "a.name:string", "b.flag:boolean"}
	if len(got) != len(want) {
		t.Fatalf("schema = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("schema = %v, want %v", got, want)
			break
		}
	}
	if specs[1].Minimum == nil || *specs[1].Minimum != 1 {
		t.Errorf("a.limit minimum = %v, want 1", specs[1].Minimum)
	}
}

func TestMockEnforcesDeclaredSpecs(t *testing.T) {
	maximum := int64(10)
	mock := New(map[string]any{"a.n": float64(1), "a.s": "x"}).
		WithSpec(configmanager.KeySpec{Key: "a.n", Type: configmanager.TypeInteger, Maximum: &maximum}).
		WithSpec(configmanager.KeySpec{Key: "a.s", Type: configmanager.TypeString, AllowedValues: []any{"x", "y"}})
	ctx := context.Background()

	for _, bad := range []any{"3", 2.5, float64(11), nil} {
		var validationErr *configmanager.ValidationError
		if err := mock.Set(ctx, "a.n", bad); !errors.As(err, &validationErr) {
			t.Errorf("Set a.n=%v err = %v, want ValidationError", bad, err)
		}
	}
	if err := mock.Set(ctx, "a.n", float64(10)); err != nil {
		t.Errorf("Set a.n=10: %v", err)
	}
	if err := mock.Set(ctx, "a.n", 7); err != nil {
		t.Errorf("Set a.n=int 7: %v", err)
	}
	if err := mock.Set(ctx, "a.s", "z"); err == nil {
		t.Error("Set a.s=z succeeded, want rejection (not in allowed values)")
	}
	if err := mock.Set(ctx, "a.s", "y"); err != nil {
		t.Errorf("Set a.s=y: %v", err)
	}
}

func TestMockWithSpecRejectsMalformedSpecs(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Error("WithSpec accepted a spec with an over-long label, want a panic")
		}
	}()
	New(map[string]any{"a.b": "x"}).WithSpec(configmanager.KeySpec{
		Key: "a.b", Type: configmanager.TypeString, Label: "this label is much longer than the forty character limit",
	})
}

func TestMockSchemaCarriesLabelAndDescription(t *testing.T) {
	mock := New(map[string]any{"a.b": "x", "a.c": "y"}).WithSpec(configmanager.KeySpec{
		Key: "a.b", Type: configmanager.TypeString, Label: "Bee", Description: "The b setting.",
	})
	specs, err := mock.Schema(context.Background())
	if err != nil {
		t.Fatalf("Schema: %v", err)
	}
	if specs[0].Label != "Bee" || specs[0].Description != "The b setting." {
		t.Errorf("a.b spec = %#v, want label and description carried through", specs[0])
	}
	if specs[1].Label != "" || specs[1].Description != "" {
		t.Errorf("a.c spec = %#v, want no label or description for an undeclared key", specs[1])
	}
}
