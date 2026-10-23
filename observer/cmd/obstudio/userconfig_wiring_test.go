package main

import (
	"crypto/sha256"
	"errors"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

func TestUserConfigSubscribeWiring(t *testing.T) {
	_, path := telemetryHome(t)
	var notified atomic.Int32
	prev := notifyConfigChanged
	notifyConfigChanged = func() { notified.Add(1) }
	t.Cleanup(func() { notifyConfigChanged = prev })

	w := openUserConfig()
	if w.manager == nil || w.api == nil || w.status == nil {
		t.Fatalf("wiring %+v", w)
	}
	m := w.manager
	waitFor := func(cond func() bool, msg string) {
		t.Helper()
		deadline := time.Now().Add(2 * time.Second)
		for !cond() {
			if time.Now().After(deadline) {
				t.Fatalf("timed out: %s", msg)
			}
			time.Sleep(10 * time.Millisecond)
		}
	}

	if err := userconfig.Set(m, userconfig.TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	waitFor(func() bool { return notified.Load() == 1 }, "notification after Set")

	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	content = append(content, "foo: 1\n"...)
	tmp := path + ".tmp-test"
	if err := os.WriteFile(tmp, content, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, path); err != nil {
		t.Fatal(err)
	}
	want := sha256.Sum256(content)
	waitFor(func() bool { return m.Get().Hash == want }, "reload of the unknown-key edit")
	if n := notified.Load(); n != 1 {
		t.Errorf("%d notifications after an unknown-key edit, want 1", n)
	}

	if err := m.Close(); err != nil {
		t.Fatal(err)
	}
	if err := userconfig.Set(m, userconfig.TelemetryEnabled, true); !errors.Is(err, userconfig.ErrClosed) {
		t.Errorf("Set after Close: %v", err)
	}
	if n := notified.Load(); n > 2 {
		t.Errorf("%d notifications after Close", n)
	}
}

func TestUserConfigWiringWithoutHome(t *testing.T) {
	t.Setenv("HOME", "")
	t.Setenv("USERPROFILE", "")
	if w := openUserConfig(); w.manager != nil || w.api != nil || w.status != nil {
		t.Errorf("wiring without a home: %+v", w)
	}
}
