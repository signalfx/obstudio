// Package gate is the one place that decides whether obstudio's own adoption
// data may leave the process right now (S-I). Allowed means: a Config Manager
// exists, ~/.obstudio/config.yaml is healthy and says telemetry.enabled: true,
// no kill switch (CI, DO_NOT_TRACK, host off) is set, and a destination is
// configured. Every other state is closed, with exactly one reason.
//
// The gate also publishes whether the user explicitly opted out (the file
// itself says enabled: false), which the install-ID owner uses to wipe the ID.
// A degraded close (broken, missing or unreadable file, absent or invalid
// value, no Manager) is never an opt-out.
package gate

import (
	"os"
	"strings"
	"sync"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// Config is what the gate needs from the Config Manager. *userconfig.Manager
// has both methods.
type Config interface {
	Get() userconfig.Snapshot
	SubscribeFile(fn func()) (cancel func())
}

// Inputs are the gate's inputs, fixed when New is called. Getenv and HostOff
// are called on every decision, never cached.
type Inputs struct {
	Config         Config              // nil, or a nil *Manager: no Manager
	Path           string              // the Manager's config.yaml path
	Getenv         func(string) string // nil: os.Getenv
	HostOff        func() bool         // nil: never off
	DestinationSet bool
}

// Reason says why a decision is closed. ReasonNone means open.
type Reason string

const (
	ReasonNone            Reason = ""
	ReasonNoManager       Reason = "no_manager"
	ReasonConfigUnhealthy Reason = "config_unhealthy"
	ReasonConsentOff      Reason = "consent_off"
	ReasonCI              Reason = "ci"
	ReasonDoNotTrack      Reason = "do_not_track"
	ReasonHostOff         Reason = "host_off"
	ReasonNoDestination   Reason = "no_destination"
)

// Decision is the result of one Decide call. Reason is ReasonNone if and only
// if Allowed.
type Decision struct {
	Allowed bool
	Reason  Reason
}

// recorded is the outcome of the gate's latest Load of the config file.
type recorded struct {
	err      error
	optedOut bool
}

type optOutSub struct{ fn func() }

// Gate decides per call whether adoption data may leave the process. A nil
// *Gate and a zero Gate are closed with ReasonNoManager.
type Gate struct {
	cfg     Config
	path    string
	getenv  func(string) string
	hostOff func() bool
	dest    bool

	// loadMu serializes loads and the opt-out subscriber calls they make.
	loadMu sync.Mutex

	mu         sync.Mutex
	rec        recorded
	closed     bool
	cancelFile func()
	subs       map[*optOutSub]struct{}
}

// New builds the gate. With a Manager it subscribes to file changes first and
// then loads the file once, so a change between the two is not missed. With
// no Manager it returns a gate that stays closed and never reads anything.
func New(in Inputs) *Gate {
	g := &Gate{path: in.Path, getenv: in.Getenv, hostOff: in.HostOff, dest: in.DestinationSet}
	if g.getenv == nil {
		g.getenv = os.Getenv
	}
	if !hasManager(in.Config) {
		return g
	}
	g.cfg = in.Config
	g.subs = map[*optOutSub]struct{}{}
	cancel := in.Config.SubscribeFile(g.load)
	g.mu.Lock()
	g.cancelFile = cancel
	g.mu.Unlock()
	g.load()
	return g
}

// hasManager reports whether c is a usable Config. A typed-nil *Manager, which
// failed wiring can return, counts as no Manager.
func hasManager(c Config) bool {
	if c == nil {
		return false
	}
	if m, ok := c.(*userconfig.Manager); ok && m == nil {
		return false
	}
	return true
}

// load reads the config file and records the result. An opt-out entry (the
// recorded state going from not opted out to opted out) calls every current
// subscriber once, after OptedOut already returns true.
func (g *Gate) load() {
	g.loadMu.Lock()
	defer g.loadMu.Unlock()
	snap, diags, err := userconfig.Load(g.path)
	optedOut := err == nil && !snap.Telemetry.Enabled && !hasTelemetryDiagnostic(diags)

	g.mu.Lock()
	if g.closed {
		g.mu.Unlock()
		return
	}
	entry := !g.rec.optedOut && optedOut
	g.rec = recorded{err: err, optedOut: optedOut}
	var subs []*optOutSub
	if entry {
		subs = make([]*optOutSub, 0, len(g.subs))
		for s := range g.subs {
			subs = append(subs, s)
		}
	}
	g.mu.Unlock()

	for _, s := range subs {
		callRecovered(s.fn)
	}
}

func callRecovered(fn func()) {
	defer func() { _ = recover() }()
	fn()
}

// hasTelemetryDiagnostic reports a diagnostic on telemetry.enabled or on the
// telemetry section: then a false value came from FailSafe, not the file.
func hasTelemetryDiagnostic(diags []userconfig.Diagnostic) bool {
	for _, d := range diags {
		if d.Key == "telemetry.enabled" || d.Key == "telemetry" {
			return true
		}
	}
	return false
}

// Decide reports whether adoption data may leave the process now. It reads
// consent, the environment and HostOff during the call and keeps nothing
// between calls. It does no file I/O of its own and never blocks on a load.
func (g *Gate) Decide() Decision {
	if g == nil || g.cfg == nil {
		return closed(ReasonNoManager)
	}
	g.mu.Lock()
	isClosed, loadErr := g.closed, g.rec.err
	g.mu.Unlock()
	switch {
	case isClosed:
		return closed(ReasonNoManager)
	case loadErr != nil:
		return closed(ReasonConfigUnhealthy)
	case !g.cfg.Get().Telemetry.Enabled:
		return closed(ReasonConsentOff)
	case isCI(g.getenv):
		return closed(ReasonCI)
	case isFlag(g.getenv("DO_NOT_TRACK")):
		return closed(ReasonDoNotTrack)
	case g.hostOff != nil && g.hostOff():
		return closed(ReasonHostOff)
	case !g.dest:
		return closed(ReasonNoDestination)
	}
	return Decision{Allowed: true, Reason: ReasonNone}
}

func closed(r Reason) Decision { return Decision{Allowed: false, Reason: r} }

// OptedOut reports whether the latest load was well-formed and the file itself
// says telemetry.enabled: false. It is false for every degraded close.
func (g *Gate) OptedOut() bool {
	if g == nil || g.cfg == nil {
		return false
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	return !g.closed && g.rec.optedOut
}

// SubscribeOptOut registers fn to be called on each opt-out entry. There is
// no initial call: subscribe, then read OptedOut. fn may run once after
// cancel returns, so it must be idempotent. cancel is idempotent.
func (g *Gate) SubscribeOptOut(fn func()) (cancel func()) {
	noop := func() {}
	if g == nil || g.cfg == nil || fn == nil {
		return noop
	}
	s := &optOutSub{fn: fn}
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.closed {
		return noop
	}
	g.subs[s] = struct{}{}
	return func() {
		g.mu.Lock()
		delete(g.subs, s)
		g.mu.Unlock()
	}
}

// Close cancels the file subscription and every opt-out subscriber. Afterwards
// Decide is closed with ReasonNoManager. It does not close the Manager.
func (g *Gate) Close() {
	if g == nil || g.cfg == nil {
		return
	}
	g.mu.Lock()
	if g.closed {
		g.mu.Unlock()
		return
	}
	g.closed = true
	cancel := g.cancelFile
	g.cancelFile = nil
	g.subs = map[*optOutSub]struct{}{}
	g.rec = recorded{}
	g.mu.Unlock()
	if cancel != nil {
		cancel()
	}
}

// isSet is a variable holding a non-blank value.
func isSet(v string) bool { return strings.TrimSpace(v) != "" }

// isFlag is a set variable whose value is neither false nor 0.
func isFlag(v string) bool {
	if !isSet(v) {
		return false
	}
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "false", "0":
		return false
	}
	return true
}

type ciMatch int

const (
	matchFlag ciMatch = iota
	matchSet
	matchBothSet
)

// ciTable is spec parameter P1 (roadmap §3.5 D5). Agent variables such as
// CLAUDECODE are deliberately absent.
var ciTable = []struct {
	vars  []string
	match ciMatch
}{
	{[]string{"CI"}, matchFlag},
	{[]string{"TF_BUILD"}, matchFlag},
	{[]string{"GITHUB_ACTIONS"}, matchFlag},
	{[]string{"APPVEYOR"}, matchFlag},
	{[]string{"TRAVIS"}, matchFlag},
	{[]string{"CIRCLECI"}, matchFlag},
	{[]string{"CODEBUILD_BUILD_ID", "AWS_REGION"}, matchBothSet},
	{[]string{"BUILD_ID", "BUILD_URL"}, matchBothSet},
	{[]string{"BUILD_ID", "PROJECT_ID"}, matchBothSet},
	{[]string{"TEAMCITY_VERSION"}, matchSet},
	{[]string{"JB_SPACE_API_URL"}, matchSet},
	{[]string{"JENKINS_URL"}, matchSet},
	{[]string{"CIRRUS_CI"}, matchFlag},
	{[]string{"CONTINUOUS_INTEGRATION"}, matchFlag},
	{[]string{"BOT"}, matchFlag},
	{[]string{"CODEBUILD_INITIATOR"}, matchSet},
}

func isCI(getenv func(string) string) bool {
	for _, row := range ciTable {
		switch row.match {
		case matchFlag:
			if isFlag(getenv(row.vars[0])) {
				return true
			}
		case matchSet:
			if isSet(getenv(row.vars[0])) {
				return true
			}
		case matchBothSet:
			if isSet(getenv(row.vars[0])) && isSet(getenv(row.vars[1])) {
				return true
			}
		}
	}
	return false
}
