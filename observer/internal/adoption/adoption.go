// Package adoption holds obstudio's own pseudonymous adoption data: three
// counters that say whether obstudio was installed, started, connected, used
// for validation, fed application data, and used from MCP or the UI. It is
// not the telemetry obstudio ingests from the user's apps; that is why the
// package is not called telemetry, even though the user-facing switch is
// telemetry.enabled.
//
// The install ID sent as obstudio.user_hash is a random UUIDv4 kept in
// ~/.obstudio/install_id. It is pseudonymous, not anonymous: it is stable for
// the install and the ingest proxy re-keys it, but it is one identifier per
// install.
//
// The package records in memory whatever the user's consent; the adoption
// gate decides per export whether anything leaves the process. A point counts
// as delivered only after an export that carried it got a 2xx.
package adoption

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/exemplar"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	"go.opentelemetry.io/otel/sdk/resource"

	"github.com/signalfx/obstudio/observer/internal/adoption/export"
	"github.com/signalfx/obstudio/observer/internal/adoption/gate"
	"github.com/signalfx/obstudio/observer/internal/store"
)

// Signal names and their single dimensions.
const (
	MetricFirstUse     = "obstudio.first_use"
	MetricActive       = "obstudio.active"
	MetricIngestActive = "obstudio.ingest_active"

	FeatureInstall       = "install"
	FeatureObserverStart = "observer_start"
	FeatureConnect       = "connect"
	FeatureValidationRun = "validation_run"
	FeatureIngest        = "ingest"

	SurfaceMCP = "mcp"
	SurfaceUI  = "ui"

	// LauncherOther is the launcher value for anything outside the known set.
	LauncherOther = "other"

	installIDFile = "install_id"
	stateFile     = "telemetry-state.json"
)

var features = map[string]bool{FeatureInstall: true, FeatureObserverStart: true, FeatureConnect: true, FeatureValidationRun: true, FeatureIngest: true}

var launchers = map[string]bool{"vscode-extension": true, "cursor-extension": true, "windsurf-extension": true, "kiro-extension": true, "cli": true}

var uuidV4 = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

// Gate is what the emitter reads from the telemetry gate (package gate):
// Decide before creating an install ID, and the opt-out state for the wipe.
type Gate interface {
	Decide() gate.Decision
	OptedOut() bool
	SubscribeOptOut(fn func()) (cancel func())
}

// Config configures New.
type Config struct {
	// Dir is ~/.obstudio. Required.
	Dir string
	// Gate is the telemetry gate. Required; a nil *gate.Gate is a closed gate.
	Gate Gate
	// Version is the build's ldflags version, sent as service.version.
	Version string
	// Launcher is the resolved OBSTUDIO_OWNER value; anything outside the
	// known set is sent as "other".
	Launcher string
	// Now is the clock; nil means time.Now. Dates are UTC.
	Now func() time.Time
}

type status int

const (
	unsent status = iota
	pending
	delivered
)

// sigKey names one signal series without its date: "first_use/<feature>",
// "active/<surface>" or "ingest_active".
type sigKey string

func firstUseKey(f string) sigKey { return sigKey("first_use/" + f) }
func activeKey(s string) sigKey   { return sigKey("active/" + s) }

const ingestKey sigKey = "ingest_active"

// Emitter owns the adoption counters, the install ID, the delivery states and
// ~/.obstudio/telemetry-state.json. A nil *Emitter ignores every event.
type Emitter struct {
	dir      string
	gate     Gate
	version  string
	launcher string
	now      func() time.Time

	mp           *sdkmetric.MeterProvider
	firstUse     metric.Int64Counter
	active       metric.Int64Counter
	ingestActive metric.Int64Counter

	flush    func(context.Context) error
	flushing atomic.Bool
	// ingestDeliveredDay is the UTC date ingest_active was last delivered:
	// the constant-time fast path for OTLP receipts.
	ingestDeliveredDay atomic.Value

	// mu serializes Decide-then-create, the wipe, events and outcomes.
	mu              sync.Mutex
	id              string
	firstUseState   map[string]status
	activePending   map[string]string // surface → UTC date
	activeDelivered map[string]string // surface → UTC date
	ingestPending   string
	ingestDelivered string
	// unexported marks a series with a recorded point the reader has not yet
	// collected. It mirrors the SDK's delta aggregator, so it survives a wipe.
	unexported   map[sigKey]bool
	cancelOptOut func()
}

// New returns an emitter. Nothing is read or written until Start.
func New(cfg Config) (*Emitter, error) {
	if cfg.Dir == "" {
		return nil, errors.New("adoption: no state directory")
	}
	if cfg.Gate == nil {
		return nil, errors.New("adoption: no gate")
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	e := &Emitter{
		dir: cfg.Dir, gate: cfg.Gate, version: cfg.Version, launcher: BoundLauncher(cfg.Launcher), now: now,
		firstUseState: map[string]status{}, activePending: map[string]string{}, activeDelivered: map[string]string{},
		unexported: map[sigKey]bool{},
	}
	e.ingestDeliveredDay.Store("")
	return e, nil
}

// BoundLauncher maps an OBSTUDIO_OWNER value to the launcher set, else "other".
func BoundLauncher(v string) string {
	if launchers[v] {
		return v
	}
	return LauncherOther
}

// SetFlush injects the adoption reader's ForceFlush, used for the one install
// flush. Call it before Start.
func (e *Emitter) SetFlush(fn func(context.Context) error) {
	if e != nil {
		e.flush = fn
	}
}

// Exporter returns the confirming exporter the adoption reader must export
// through. It wraps next, the adoption exporter from package export.
func (e *Emitter) Exporter(next sdkmetric.Exporter) sdkmetric.Exporter {
	return &confirming{e: e, next: next}
}

// Start builds the adoption meter provider over reader, registers the three
// counters, applies a pending opt-out wipe, reads the install ID and state,
// and, with no valid ID, starts ID creation off the startup path. It does not
// wait for creation or for the install flush.
func (e *Emitter) Start(reader sdkmetric.Reader) error {
	if e == nil {
		return nil
	}
	// The resource set here is replaced at export; exemplars are off because
	// the ingest proxy drops any point that carries one.
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(reader),
		sdkmetric.WithResource(resource.Empty()),
		sdkmetric.WithExemplarFilter(exemplar.AlwaysOffFilter),
	)
	meter := mp.Meter("github.com/signalfx/obstudio/observer/internal/adoption")
	firstUse, err := meter.Int64Counter(MetricFirstUse, metric.WithUnit("{event}"))
	if err != nil {
		return err
	}
	active, err := meter.Int64Counter(MetricActive, metric.WithUnit("{day}"))
	if err != nil {
		return err
	}
	ingestActive, err := meter.Int64Counter(MetricIngestActive, metric.WithUnit("{day}"))
	if err != nil {
		return err
	}
	e.mu.Lock()
	e.mp, e.firstUse, e.active, e.ingestActive = mp, firstUse, active, ingestActive
	e.mu.Unlock()

	e.cancelOptOut = e.gate.SubscribeOptOut(e.wipe)
	if e.gate.OptedOut() {
		e.wipe()
	}

	e.mu.Lock()
	id := readInstallID(filepath.Join(e.dir, installIDFile))
	installPending := false
	if id != "" {
		e.id = id
		e.loadStateLocked()
		installPending = e.firstUseState[FeatureInstall] == pending
	}
	e.mu.Unlock()

	if id == "" {
		go e.createAtStart()
	} else if installPending {
		e.requestInstallFlush()
	}
	return nil
}

// Shutdown runs the clean-exit flush through the reader and stops it, bounded
// by ctx.
func (e *Emitter) Shutdown(ctx context.Context) error {
	if e == nil || e.mp == nil {
		return nil
	}
	if e.cancelOptOut != nil {
		e.cancelOptOut()
	}
	return e.mp.Shutdown(ctx)
}

func (e *Emitter) today() string { return e.now().UTC().Format("2006-01-02") }

// ObserverStarted records first_use{observer_start}: listeners bound, serving.
func (e *Emitter) ObserverStarted() { e.firstUseEvent(FeatureObserverStart) }

// Connected records first_use{connect}: a connect to a Splunk Observability
// Cloud org returned success.
func (e *Emitter) Connected() { e.firstUseEvent(FeatureConnect) }

// ValidationRun records first_use{validation_run}: a validation run executed,
// whatever its verdict.
func (e *Emitter) ValidationRun() { e.firstUseEvent(FeatureValidationRun) }

// ActiveMCP records active{mcp}: a tools/call served on POST /mcp or stdio.
func (e *Emitter) ActiveMCP() { e.activeEvent(SurfaceMCP) }

// ActiveUI records active{ui}: a request carrying X-Obstudio-Surface: ui.
func (e *Emitter) ActiveUI() { e.activeEvent(SurfaceUI) }

func (e *Emitter) firstUseEvent(feature string) {
	if e == nil {
		return
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.firstUseState[feature] == unsent {
		e.makeFirstUsePendingLocked(feature)
	}
}

func (e *Emitter) activeEvent(surface string) {
	if e == nil {
		return
	}
	today := e.today()
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.activeDelivered[surface] == today || e.activePending[surface] == today {
		return
	}
	e.activePending[surface] = today
	e.recordLocked(activeKey(surface))
}

// OTLPReceipt is the ingest hook the store calls for each accepted
// application payload. Once today's ingest_active is delivered it returns
// after one atomic read.
func (e *Emitter) OTLPReceipt(r store.Receipt) {
	if e == nil {
		return
	}
	today := e.today()
	if day, _ := e.ingestDeliveredDay.Load().(string); day == today {
		return
	}
	if !qualifyingReceipt(r) {
		return
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.firstUseState[FeatureIngest] == unsent {
		e.makeFirstUsePendingLocked(FeatureIngest)
	}
	if e.ingestDelivered != today && e.ingestPending != today {
		e.ingestPending = today
		e.recordLocked(ingestKey)
	}
}

// qualifyingReceipt reports a payload with at least one record that is not
// obstudio's own self-telemetry and not agent-native.
func qualifyingReceipt(r store.Receipt) bool {
	for _, s := range r.Spans {
		if !selfTelemetry(s.Resource) && !store.IsAgentOrigin(s) {
			return true
		}
	}
	for _, m := range r.Metrics {
		if !selfTelemetry(m.Resource) && !store.IsAgentOrigin(m) {
			return true
		}
	}
	for _, l := range r.Logs {
		if !selfTelemetry(l.Resource) && !store.IsAgentOrigin(l) {
			return true
		}
	}
	return false
}

func selfTelemetry(r store.Resource) bool { return r.ServiceName == "obstudio" }

func (e *Emitter) makeFirstUsePendingLocked(feature string) {
	e.firstUseState[feature] = pending
	e.recordLocked(firstUseKey(feature))
}

// recordLocked records one point of value 1 for k unless one is already
// waiting for the reader, so every exported point has value 1.
func (e *Emitter) recordLocked(k sigKey) {
	if e.unexported[k] || e.firstUse == nil {
		return
	}
	e.unexported[k] = true
	ctx := context.Background()
	switch {
	case k == ingestKey:
		e.ingestActive.Add(ctx, 1)
	case strings.HasPrefix(string(k), "active/"):
		e.active.Add(ctx, 1, metric.WithAttributes(attribute.String("surface", strings.TrimPrefix(string(k), "active/"))))
	default:
		e.firstUse.Add(ctx, 1, metric.WithAttributes(attribute.String("feature", strings.TrimPrefix(string(k), "first_use/"))))
	}
}

// createAtStart is the start-time creation, run in its own goroutine.
func (e *Emitter) createAtStart() {
	e.mu.Lock()
	created := e.id == "" && e.gate.Decide().Allowed && e.createLocked()
	e.mu.Unlock()
	if created {
		e.requestInstallFlush()
	}
}

// createLocked creates the install ID. It runs only right after an open
// Decide. On any failure it holds no ID and returns false.
func (e *Emitter) createLocked() bool {
	if err := ensureDir(e.dir); err != nil {
		return false
	}
	id, err := newUUIDv4()
	if err != nil {
		return false
	}
	idPath := filepath.Join(e.dir, installIDFile)
	if err := writeAtomic(idPath, []byte(id+"\n")); err != nil {
		return false
	}
	initial := stateDoc{FirstUse: map[string]string{FeatureInstall: "pending"}, Active: map[string]string{}}
	if err := writeState(filepath.Join(e.dir, stateFile), initial); err != nil {
		_ = os.Remove(idPath)
		return false
	}
	e.id = id
	for f, s := range e.firstUseState {
		if s == delivered {
			delete(e.firstUseState, f)
		}
	}
	e.activeDelivered = map[string]string{}
	e.ingestDelivered = ""
	e.ingestDeliveredDay.Store("")
	e.makeFirstUsePendingLocked(FeatureInstall)
	return true
}

// requestInstallFlush asks for one forced export in its own goroutine,
// bounded by export.FlushTimeout. At most one is in flight.
func (e *Emitter) requestInstallFlush() {
	f := e.flush
	if f == nil || !e.flushing.CompareAndSwap(false, true) {
		return
	}
	go func() {
		defer e.flushing.Store(false)
		ctx, cancel := context.WithTimeout(context.Background(), export.FlushTimeout)
		defer cancel()
		_ = f(ctx)
	}()
}

// wipe is the opt-out wipe: delete both files and drop the ID and every
// pending and delivered state. It is idempotent.
func (e *Emitter) wipe() {
	e.mu.Lock()
	defer e.mu.Unlock()
	_ = removeIfExists(filepath.Join(e.dir, installIDFile))
	_ = removeIfExists(filepath.Join(e.dir, stateFile))
	e.id = ""
	e.firstUseState = map[string]status{}
	e.activePending = map[string]string{}
	e.activeDelivered = map[string]string{}
	e.ingestPending = ""
	e.ingestDelivered = ""
	e.ingestDeliveredDay.Store("")
}

// batchKey is one series in an exported batch, with the date its pending key
// had at collection time.
type batchKey struct {
	k    sigKey
	date string
}

type outcome int

const (
	outcomeSent outcome = iota
	outcomeFailed
	outcomeDropped
)

// confirming is the exporter the adoption reader calls. It stamps the batch
// with the six resource attributes and the current install ID, forwards it
// to the adoption exporter, and applies the export outcome to the delivery
// states.
type confirming struct {
	e    *Emitter
	next sdkmetric.Exporter
}

func (c *confirming) Temporality(sdkmetric.InstrumentKind) metricdata.Temporality {
	return metricdata.DeltaTemporality
}

func (c *confirming) Aggregation(k sdkmetric.InstrumentKind) sdkmetric.Aggregation {
	return sdkmetric.DefaultAggregationSelector(k)
}

func (c *confirming) ForceFlush(ctx context.Context) error { return c.next.ForceFlush(ctx) }
func (c *confirming) Shutdown(ctx context.Context) error   { return c.next.Shutdown(ctx) }

func (c *confirming) Export(ctx context.Context, rm *metricdata.ResourceMetrics) error {
	e := c.e
	e.mu.Lock()
	created := false
	if e.id == "" && e.gate.Decide().Allowed {
		created = e.createLocked()
	}
	id := e.id
	keys, scopes := e.collectLocked(rm)
	if id == "" {
		e.applyLocked(keys, outcomeDropped)
		e.mu.Unlock()
		return nil
	}
	e.mu.Unlock()
	if created {
		e.requestInstallFlush()
	}
	if len(keys) == 0 {
		return nil
	}

	out := &metricdata.ResourceMetrics{Resource: e.resourceFor(id), ScopeMetrics: scopes}
	err := c.next.Export(ctx, out)
	result := outcomeSent
	switch {
	case err == nil:
	case errors.Is(err, export.ErrDropped):
		result = outcomeDropped
	default:
		result = outcomeFailed
	}

	e.mu.Lock()
	defer e.mu.Unlock()
	if e.id != id {
		// A wipe or a new ID happened during the export: discard.
		return err
	}
	e.applyLocked(keys, result)
	if result != outcomeDropped {
		e.writeStateLocked()
	}
	return err
}

// collectLocked reads the batch the reader collected: every series in it is
// no longer waiting for the reader. It keeps only points whose key is still
// pending (a wipe drops the rest) and returns those keys with their dates.
func (e *Emitter) collectLocked(rm *metricdata.ResourceMetrics) ([]batchKey, []metricdata.ScopeMetrics) {
	var keys []batchKey
	var scopes []metricdata.ScopeMetrics
	for _, sm := range rm.ScopeMetrics {
		var metrics []metricdata.Metrics
		for _, m := range sm.Metrics {
			sum, ok := m.Data.(metricdata.Sum[int64])
			if !ok {
				continue
			}
			var kept []metricdata.DataPoint[int64]
			for _, dp := range sum.DataPoints {
				bk, ok := e.keyOf(m.Name, dp.Attributes)
				if !ok {
					continue
				}
				e.unexported[bk.k] = false
				if bk.date == "" && !strings.HasPrefix(string(bk.k), "first_use/") {
					continue // not pending: dropped by a wipe
				}
				if strings.HasPrefix(string(bk.k), "first_use/") && e.firstUseState[strings.TrimPrefix(string(bk.k), "first_use/")] != pending {
					continue
				}
				keys = append(keys, bk)
				kept = append(kept, dp)
			}
			if len(kept) > 0 {
				sum.DataPoints = kept
				m.Data = sum
				metrics = append(metrics, m)
			}
		}
		if len(metrics) > 0 {
			sm.Metrics = metrics
			scopes = append(scopes, sm)
		}
	}
	return keys, scopes
}

func (e *Emitter) keyOf(name string, attrs attribute.Set) (batchKey, bool) {
	switch name {
	case MetricFirstUse:
		v, _ := attrs.Value("feature")
		if !features[v.AsString()] {
			return batchKey{}, false
		}
		return batchKey{k: firstUseKey(v.AsString())}, true
	case MetricActive:
		v, _ := attrs.Value("surface")
		s := v.AsString()
		if s != SurfaceMCP && s != SurfaceUI {
			return batchKey{}, false
		}
		return batchKey{k: activeKey(s), date: e.activePending[s]}, true
	case MetricIngestActive:
		return batchKey{k: ingestKey, date: e.ingestPending}, true
	}
	return batchKey{}, false
}

// applyLocked applies one export outcome to the keys whose points it carried.
func (e *Emitter) applyLocked(keys []batchKey, result outcome) {
	today := e.today()
	for _, bk := range keys {
		switch {
		case strings.HasPrefix(string(bk.k), "first_use/"):
			f := strings.TrimPrefix(string(bk.k), "first_use/")
			if e.firstUseState[f] != pending {
				continue
			}
			if result == outcomeSent {
				e.firstUseState[f] = delivered
			} else {
				e.recordLocked(bk.k)
			}
		case bk.k == ingestKey:
			if e.ingestPending != bk.date {
				if result == outcomeSent && bk.date > e.ingestDelivered {
					e.ingestDelivered = bk.date
				}
				continue
			}
			switch {
			case result == outcomeSent:
				e.ingestDelivered = bk.date
				e.ingestPending = ""
			case bk.date != today:
				e.ingestPending = "" // lapsed at UTC midnight
			default:
				e.recordLocked(bk.k)
			}
		default:
			s := strings.TrimPrefix(string(bk.k), "active/")
			if e.activePending[s] != bk.date {
				if result == outcomeSent && bk.date > e.activeDelivered[s] {
					e.activeDelivered[s] = bk.date
				}
				continue
			}
			switch {
			case result == outcomeSent:
				e.activeDelivered[s] = bk.date
				delete(e.activePending, s)
			case bk.date != today:
				delete(e.activePending, s)
			default:
				e.recordLocked(bk.k)
			}
		}
	}
	e.ingestDeliveredDay.Store(e.ingestDelivered)
}

// resourceFor is the whole batch resource: exactly six keys, none from the
// environment or the SDK defaults.
func (e *Emitter) resourceFor(id string) *resource.Resource {
	return resource.NewSchemaless(
		attribute.String("service.name", "obstudio"),
		attribute.String("service.version", e.version),
		attribute.String("os.type", osType(runtime.GOOS)),
		attribute.String("host.arch", hostArch(runtime.GOARCH)),
		attribute.String("obstudio.launcher", e.launcher),
		attribute.String("obstudio.user_hash", id),
	)
}

// osType maps GOOS to the OTel semantic-convention os.type value.
func osType(goos string) string {
	switch goos {
	case "dragonfly":
		return "dragonflybsd"
	case "illumos":
		return "solaris"
	case "zos":
		return "z_os"
	}
	return goos
}

// hostArch maps GOARCH to the OTel semantic-convention host.arch value.
func hostArch(goarch string) string {
	switch goarch {
	case "386":
		return "x86"
	case "arm":
		return "arm32"
	case "ppc64le":
		return "ppc64"
	}
	return goarch
}

// stateDoc is the content of ~/.obstudio/telemetry-state.json.
type stateDoc struct {
	FirstUse     map[string]string `json:"first_use"`
	Active       map[string]string `json:"active"`
	IngestActive string            `json:"ingest_active,omitempty"`
}

var dateRE = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

// loadStateLocked reads the state file. Anything missing, malformed or
// unknown reads as unsent. Each pending first_use is recorded again.
func (e *Emitter) loadStateLocked() {
	data, err := os.ReadFile(filepath.Join(e.dir, stateFile))
	if err != nil {
		return
	}
	var doc stateDoc
	if json.Unmarshal(data, &doc) != nil {
		return
	}
	for f, v := range doc.FirstUse {
		if !features[f] {
			continue
		}
		switch v {
		case "delivered":
			e.firstUseState[f] = delivered
		case "pending":
			e.makeFirstUsePendingLocked(f)
		}
	}
	for s, d := range doc.Active {
		if (s == SurfaceMCP || s == SurfaceUI) && dateRE.MatchString(d) {
			e.activeDelivered[s] = d
		}
	}
	if dateRE.MatchString(doc.IngestActive) {
		e.ingestDelivered = doc.IngestActive
		e.ingestDeliveredDay.Store(doc.IngestActive)
	}
}

// writeStateLocked writes the state file from memory. Only called with a
// valid ID held.
func (e *Emitter) writeStateLocked() {
	doc := stateDoc{FirstUse: map[string]string{}, Active: map[string]string{}, IngestActive: e.ingestDelivered}
	for f, s := range e.firstUseState {
		switch s {
		case pending:
			doc.FirstUse[f] = "pending"
		case delivered:
			doc.FirstUse[f] = "delivered"
		}
	}
	for s, d := range e.activeDelivered {
		doc.Active[s] = d
	}
	_ = writeState(filepath.Join(e.dir, stateFile), doc)
}

func writeState(path string, doc stateDoc) error {
	data, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	return writeAtomic(path, append(data, '\n'))
}

// readInstallID returns the trimmed content of path if it is a valid
// lowercase UUIDv4, else "".
func readInstallID(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	id := strings.TrimSpace(string(data))
	if !uuidV4.MatchString(id) {
		return ""
	}
	return id
}

// newUUIDv4 returns a random version-4 UUID in canonical lowercase form. Its
// only input is crypto/rand.
func newUUIDv4() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	h := hex.EncodeToString(b[:])
	return fmt.Sprintf("%s-%s-%s-%s-%s", h[0:8], h[8:12], h[12:16], h[16:20], h[20:32]), nil
}

// ensureDir creates dir with mode 0700 if it does not exist. An existing
// directory's mode is left alone.
func ensureDir(dir string) error {
	if fi, err := os.Stat(dir); err == nil {
		if !fi.IsDir() {
			return fmt.Errorf("adoption: %s is not a directory", dir)
		}
		return nil
	}
	return os.MkdirAll(dir, 0o700)
}

// writeAtomic writes data to path with mode 0600 through a temp file in the
// same directory and a rename.
func writeAtomic(path string, data []byte) error {
	dir := filepath.Dir(path)
	f, err := os.CreateTemp(dir, "."+filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if err := f.Chmod(0o600); err != nil {
		f.Close()
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func removeIfExists(path string) error {
	if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	return nil
}
