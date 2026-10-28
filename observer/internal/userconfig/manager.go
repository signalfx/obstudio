package userconfig

import (
	"errors"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// DebounceInterval is how long the file must be quiet before a change is
// read.
const DebounceInterval = 100 * time.Millisecond

var (
	ErrInvalidPath = errors.New("userconfig: path must be absolute")
	ErrClosed      = errors.New("userconfig: manager closed")
)

type stopper interface{ Stop() bool }

type options struct {
	logf       func(format string, args ...any)
	afterFunc  func(time.Duration, func()) stopper
	now        func() time.Time
	newWatcher func() (watcher, error)
	noWatch    bool
	onReload   func()
	afterRead  func()
}

type Option func(*options)

// WithLogf sends the Manager's log lines to logf instead of log.Printf.
func WithLogf(logf func(format string, args ...any)) Option {
	return func(o *options) { o.logf = logf }
}

// Event reports an effective change of one or more settings.
type Event struct {
	Old, New   Snapshot
	Generation uint64
}

// Affects reports whether the key, or any key in the section, changed
// between Old and New.
func (e Event) Affects(s Selector) bool {
	if s == nil {
		return false
	}
	p := s.selectorPath()
	if p == "" {
		return false
	}
	for _, c := range changedPaths(e.Old.Settings, e.New.Settings) {
		if c == p || strings.HasPrefix(c, p+".") {
			return true
		}
	}
	return false
}

type stampKind int

const (
	stampAbsent stampKind = iota + 1
	stampUnreadable
	stampPresent
)

type stamp struct {
	kind stampKind
	info os.FileInfo
}

func takeStamp(path string) stamp {
	info, err := os.Stat(path)
	switch {
	case err == nil:
		return stamp{kind: stampPresent, info: info}
	case errors.Is(err, fs.ErrNotExist):
		return stamp{kind: stampAbsent}
	default:
		return stamp{kind: stampUnreadable}
	}
}

func (a stamp) equal(b stamp) bool {
	if a.kind != b.kind {
		return false
	}
	if a.kind != stampPresent {
		return true
	}
	return a.info.ModTime().Equal(b.info.ModTime()) && a.info.Size() == b.info.Size() && os.SameFile(a.info, b.info)
}

// settling reports a file modified less than DebounceInterval ago, which an
// editor may still be writing.
func (a stamp) settling(now time.Time) bool {
	if a.kind != stampPresent {
		return false
	}
	age := now.Sub(a.info.ModTime())
	return age >= 0 && age < DebounceInterval
}

// loadResult is what one Load call returned: the snapshot hash, or the
// error's kind and text. Diagnostics are left out because they follow from
// the bytes, so an equal hash means equal diagnostics.
type loadResult struct {
	ok   bool
	hash [32]byte
	kind errKind
	text string
}

type errKind int

const (
	errMissing errKind = iota + 1
	errSyntaxKind
	errRead
)

func resultOf(snap Snapshot, err error) loadResult {
	switch {
	case err == nil:
		return loadResult{ok: true, hash: snap.Hash}
	case errors.Is(err, fs.ErrNotExist):
		return loadResult{kind: errMissing, text: err.Error()}
	case errors.Is(err, ErrSyntax):
		return loadResult{kind: errSyntaxKind, text: err.Error()}
	default:
		return loadResult{kind: errRead, text: err.Error()}
	}
}

// Manager holds the current settings of one config file and keeps them in
// step with the file.
type Manager struct {
	path, dir string
	opts      options

	snap atomic.Pointer[Snapshot]

	// reloadMu serializes reloads and guards recorded, result and
	// generation.
	reloadMu   sync.Mutex
	recorded   stamp
	result     loadResult
	generation uint64

	// dispatchMu is taken before reloadMu is released, so events and file
	// notifications reach the mailboxes in reload order.
	dispatchMu sync.Mutex

	// writeMu serializes Update within this process; taken before reloadMu.
	writeMu sync.Mutex

	watched atomic.Bool
	closed  atomic.Bool

	watchMu sync.Mutex
	w       watcher
	quit    chan struct{}
	timer   stopper

	subMu    sync.Mutex
	subs     map[*subscriber]struct{}
	fileSubs map[*fileSubscriber]struct{}
}

// NewManager opens the config file at path, creating it if absent, and
// starts watching it. It fails only for an empty or relative path; file and
// watcher problems give a fail-safe or unwatched Manager instead.
func NewManager(path string, opts ...Option) (*Manager, error) {
	if path == "" || !filepath.IsAbs(path) {
		return nil, ErrInvalidPath
	}
	o := options{
		logf:       log.Printf,
		afterFunc:  func(d time.Duration, f func()) stopper { return time.AfterFunc(d, f) },
		now:        time.Now,
		newWatcher: newFSWatcher,
		onReload:   func() {},
		afterRead:  func() {},
	}
	for _, opt := range opts {
		opt(&o)
	}
	m := &Manager{
		path:     filepath.Clean(path),
		dir:      filepath.Clean(filepath.Dir(path)),
		opts:     o,
		subs:     map[*subscriber]struct{}{},
		fileSubs: map[*fileSubscriber]struct{}{},
	}

	_, scaffoldErr := EnsureScaffold(m.path)
	m.recorded = takeStamp(m.path)
	snap, diags, loadErr := Load(m.path)
	m.result = resultOf(snap, loadErr)
	if err := errors.Join(scaffoldErr, loadErr); err != nil {
		snap = FailSafeSnapshot()
		m.opts.logf("[userconfig] %s could not be read, using fail-safe settings (%s): %v", m.path, failSafeSummary(), err)
	} else {
		m.logDiagnostics(diags)
	}
	m.snap.Store(&snap)

	if !o.noWatch {
		m.startWatch()
	}
	return m, nil
}

func (m *Manager) logDiagnostics(diags []Diagnostic) {
	for _, d := range diags {
		m.opts.logf("[userconfig] %s: %s (%s)", m.path, d.Message, d.Kind)
	}
}

// Get returns the current settings. While the file is watched it is a single
// atomic load; otherwise it first re-reads the file if it changed.
func (m *Manager) Get() Snapshot {
	if !m.closed.Load() && !m.watched.Load() {
		m.revalidate()
	}
	return *m.snap.Load()
}

func (m *Manager) revalidate() {
	s := takeStamp(m.path)
	m.reloadMu.Lock()
	same := s.equal(m.recorded)
	m.reloadMu.Unlock()
	if same || s.settling(m.opts.now()) {
		return
	}
	m.reload()
}

func (m *Manager) reload() {
	if m.closed.Load() {
		return
	}
	m.opts.onReload()
	m.reloadMu.Lock()
	if m.closed.Load() {
		m.reloadMu.Unlock()
		return
	}
	// The stamp is taken before the read, so a write landing in between
	// leaves an older recorded stamp and is picked up next time.
	st := takeStamp(m.path)
	snap, diags, err := Load(m.path)
	m.opts.afterRead()
	m.recorded = st
	res := resultOf(snap, err)
	fileChanged := res != m.result
	m.result = res

	var ev *Event
	cur := m.snap.Load()
	switch {
	case err != nil:
		m.opts.logf("[userconfig] %s could not be read, keeping current settings: %v", m.path, err)
	case snap.Hash == cur.Hash:
	default:
		m.snap.Store(&snap)
		m.logDiagnostics(diags)
		if len(changedPaths(cur.Settings, snap.Settings)) > 0 {
			m.generation++
			ev = &Event{Old: *cur, New: snap, Generation: m.generation}
		}
	}
	if ev == nil && !fileChanged {
		m.reloadMu.Unlock()
		return
	}
	m.dispatchMu.Lock()
	m.reloadMu.Unlock()
	if ev != nil {
		m.dispatch(*ev)
	}
	if fileChanged {
		m.dispatchFile()
	}
	m.dispatchMu.Unlock()
}

// Update writes every entry of c to the file and returns once Get reflects
// the write.
func Update(m *Manager, c Changes) error {
	if m.closed.Load() {
		return ErrClosed
	}
	if c.Len() == 0 {
		return nil
	}
	m.writeMu.Lock()
	defer m.writeMu.Unlock()
	if m.closed.Load() {
		return ErrClosed
	}
	if err := WriteChanges(m.path, c); err != nil {
		return err
	}
	m.reload()
	return nil
}

// Set writes one key; see Update.
func Set[T Value](m *Manager, k Key[T], v T) error {
	var c Changes
	Put(&c, k, v)
	return Update(m, c)
}

type subscriber struct {
	fn   func(Event)
	logf func(format string, args ...any)
	wake chan struct{}

	mu        sync.Mutex
	pending   *Event
	cancelled bool
}

// Subscribe calls fn on its own goroutine for each later Event. A slow fn
// delays only itself and sees the changes it missed coalesced into one Event.
// fn may run once after cancel returns, so it must be idempotent.
func (m *Manager) Subscribe(fn func(Event)) (cancel func()) {
	if m.closed.Load() {
		return func() {}
	}
	s := &subscriber{fn: fn, logf: m.opts.logf, wake: make(chan struct{}, 1)}
	m.subMu.Lock()
	if m.closed.Load() {
		m.subMu.Unlock()
		return func() {}
	}
	m.subs[s] = struct{}{}
	m.subMu.Unlock()
	go s.run()
	return func() {
		m.subMu.Lock()
		delete(m.subs, s)
		m.subMu.Unlock()
		s.cancel()
	}
}

func (m *Manager) dispatch(ev Event) {
	m.subMu.Lock()
	subs := make([]*subscriber, 0, len(m.subs))
	for s := range m.subs {
		subs = append(subs, s)
	}
	m.subMu.Unlock()
	for _, s := range subs {
		s.deliver(ev)
	}
}

func (s *subscriber) deliver(ev Event) {
	s.mu.Lock()
	if s.cancelled {
		s.mu.Unlock()
		return
	}
	if s.pending != nil {
		ev = Event{Old: s.pending.Old, New: ev.New, Generation: ev.Generation}
	}
	s.pending = &ev
	s.mu.Unlock()
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

func (s *subscriber) cancel() {
	s.mu.Lock()
	s.cancelled = true
	s.pending = nil
	s.mu.Unlock()
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

func (s *subscriber) run() {
	for range s.wake {
		s.mu.Lock()
		if s.cancelled {
			s.mu.Unlock()
			return
		}
		ev := s.pending
		s.pending = nil
		s.mu.Unlock()
		if ev != nil {
			s.invoke(*ev)
		}
	}
}

func (s *subscriber) invoke(ev Event) {
	defer func() {
		if r := recover(); r != nil {
			s.logf("[userconfig] subscriber panicked: %v", r)
		}
	}()
	s.fn(ev)
}

type fileSubscriber struct {
	fn   func()
	logf func(format string, args ...any)
	wake chan struct{}

	mu        sync.Mutex
	pending   bool
	cancelled bool
}

// SubscribeFile calls fn on its own goroutine after each later reload whose
// result (the file's hash, or the error reading it) differs from the
// previous reload's. It fires for changes that leave the settings as they
// were, such as a broken file, its fix, or an unknown key. Notifications
// that arrive while fn runs are merged into one call. fn may run once after
// cancel returns, so it must be idempotent.
func (m *Manager) SubscribeFile(fn func()) (cancel func()) {
	if m.closed.Load() {
		return func() {}
	}
	s := &fileSubscriber{fn: fn, logf: m.opts.logf, wake: make(chan struct{}, 1)}
	m.subMu.Lock()
	if m.closed.Load() {
		m.subMu.Unlock()
		return func() {}
	}
	m.fileSubs[s] = struct{}{}
	m.subMu.Unlock()
	go s.run()
	return func() {
		m.subMu.Lock()
		delete(m.fileSubs, s)
		m.subMu.Unlock()
		s.cancel()
	}
}

func (m *Manager) dispatchFile() {
	m.subMu.Lock()
	subs := make([]*fileSubscriber, 0, len(m.fileSubs))
	for s := range m.fileSubs {
		subs = append(subs, s)
	}
	m.subMu.Unlock()
	for _, s := range subs {
		s.deliver()
	}
}

func (s *fileSubscriber) deliver() {
	s.mu.Lock()
	if s.cancelled {
		s.mu.Unlock()
		return
	}
	s.pending = true
	s.mu.Unlock()
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

func (s *fileSubscriber) cancel() {
	s.mu.Lock()
	s.cancelled = true
	s.pending = false
	s.mu.Unlock()
	select {
	case s.wake <- struct{}{}:
	default:
	}
}

func (s *fileSubscriber) run() {
	for range s.wake {
		s.mu.Lock()
		if s.cancelled {
			s.mu.Unlock()
			return
		}
		pending := s.pending
		s.pending = false
		s.mu.Unlock()
		if pending {
			s.invoke()
		}
	}
}

func (s *fileSubscriber) invoke() {
	defer func() {
		if r := recover(); r != nil {
			s.logf("[userconfig] file subscriber panicked: %v", r)
		}
	}()
	s.fn()
}

// Close stops watching and cancels every subscriber. It does not wait for a
// callback in progress, so a callback may call it.
func (m *Manager) Close() error {
	if !m.closed.CompareAndSwap(false, true) {
		return nil
	}
	err := m.stopWatch()
	// Wait out a reload in progress; later reloads see closed and return.
	m.reloadMu.Lock()
	m.reloadMu.Unlock()
	m.subMu.Lock()
	subs, fileSubs := m.subs, m.fileSubs
	m.subs = map[*subscriber]struct{}{}
	m.fileSubs = map[*fileSubscriber]struct{}{}
	m.subMu.Unlock()
	for s := range subs {
		s.cancel()
	}
	for s := range fileSubs {
		s.cancel()
	}
	return err
}
