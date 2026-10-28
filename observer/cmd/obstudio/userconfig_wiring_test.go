package main

import (
	"bytes"
	"errors"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

func TestUserConfigFileStateWiring(t *testing.T) {
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
	waitFor := func(n int32, msg string) {
		t.Helper()
		deadline := time.Now().Add(2 * time.Second)
		for notified.Load() != n {
			if time.Now().After(deadline) {
				t.Fatalf("timed out: %s: %d notifications, want %d", msg, notified.Load(), n)
			}
			time.Sleep(10 * time.Millisecond)
		}
	}
	handWrite := func(content []byte) {
		t.Helper()
		tmp := path + ".tmp-test"
		if err := os.WriteFile(tmp, content, 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(tmp, path); err != nil {
			t.Fatal(err)
		}
	}

	if err := userconfig.Set(m, userconfig.TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	waitFor(1, "value")

	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	afterB := append(content, "foo: 1\n"...)
	handWrite(afterB)
	waitFor(2, "unknown-key")

	handWrite([]byte("telemetry: [unclosed"))
	waitFor(3, "broken")
	if m.Get().Telemetry.Enabled {
		t.Error("broken: last-good not kept")
	}

	handWrite(afterB)
	waitFor(4, "fixed-same-values")

	src, err := os.ReadFile("userconfig_wiring.go")
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(src, []byte(".Subscribe(")) {
		t.Error("one-callback: the wiring calls Subscribe")
	}

	if err := m.Close(); err != nil {
		t.Fatal(err)
	}
	if err := userconfig.Set(m, userconfig.TelemetryEnabled, true); !errors.Is(err, userconfig.ErrClosed) {
		t.Errorf("close-cancels: Set after Close: %v", err)
	}
	if n := notified.Load(); n > 5 {
		t.Errorf("close-cancels: %d notifications after Close", n)
	}
}

func TestUserConfigWiringWithoutHome(t *testing.T) {
	t.Setenv("HOME", "")
	t.Setenv("USERPROFILE", "")
	if w := openUserConfig(); w.manager != nil || w.api != nil || w.status != nil {
		t.Errorf("wiring without a home: %+v", w)
	}
}
