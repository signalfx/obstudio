package userconfig

import (
	"path/filepath"

	"github.com/fsnotify/fsnotify"
)

type watcher interface {
	Add(string) error
	Events() <-chan fsnotify.Event
	Errors() <-chan error
	Close() error
}

type fsWatcher struct{ w *fsnotify.Watcher }

func newFSWatcher() (watcher, error) {
	w, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}
	return fsWatcher{w}, nil
}

func (f fsWatcher) Add(name string) error         { return f.w.Add(name) }
func (f fsWatcher) Events() <-chan fsnotify.Event { return f.w.Events }
func (f fsWatcher) Errors() <-chan error          { return f.w.Errors }
func (f fsWatcher) Close() error                  { return f.w.Close() }

// startWatch watches the directory rather than the file, because editors and
// atomic writers replace the file and a watch on it would be lost.
func (m *Manager) startWatch() {
	w, err := m.opts.newWatcher()
	if err != nil {
		m.opts.logf("[userconfig] cannot watch %s, changes are read when settings are read: %v", m.path, err)
		return
	}
	if err := w.Add(m.dir); err != nil {
		w.Close()
		m.opts.logf("[userconfig] cannot watch %s, changes are read when settings are read: %v", m.path, err)
		return
	}
	quit := make(chan struct{})
	m.watchMu.Lock()
	m.w, m.quit = w, quit
	m.watched.Store(true)
	m.watchMu.Unlock()
	go m.watchLoop(w, quit)
}

func (m *Manager) watchLoop(w watcher, quit <-chan struct{}) {
	events, errs := w.Events(), w.Errors()
	for {
		select {
		case <-quit:
			return
		case ev, ok := <-events:
			if !ok {
				m.onWatchClosed()
				return
			}
			m.onWatchEvent(ev)
		case err, ok := <-errs:
			if !ok {
				errs = nil
				continue
			}
			m.onWatchError(err)
		}
	}
}

func (m *Manager) isWatched() bool { return m.watched.Load() }

func (m *Manager) onWatchEvent(ev fsnotify.Event) {
	if m.closed.Load() || !m.watched.Load() {
		return
	}
	name := filepath.Clean(ev.Name)
	if name == m.dir {
		if ev.Op.Has(fsnotify.Remove) || ev.Op.Has(fsnotify.Rename) {
			m.switchUnwatched("config directory " + m.dir + " was removed or renamed")
		}
		return
	}
	if name != m.path {
		return
	}
	m.arm()
}

func (m *Manager) onWatchError(err error) {
	if m.closed.Load() {
		return
	}
	m.opts.logf("[userconfig] watcher error, re-reading %s: %v", m.path, err)
	m.arm()
}

func (m *Manager) onWatchClosed() {
	if m.closed.Load() {
		return
	}
	m.switchUnwatched("config watcher stopped")
}

func (m *Manager) arm() {
	m.watchMu.Lock()
	defer m.watchMu.Unlock()
	if m.closed.Load() {
		return
	}
	if m.timer != nil {
		m.timer.Stop()
	}
	m.timer = m.opts.afterFunc(DebounceInterval, m.reload)
}

// switchUnwatched gives up the watch for good; Get then re-reads a changed
// file itself.
func (m *Manager) switchUnwatched(reason string) {
	m.watchMu.Lock()
	if !m.watched.Load() || m.closed.Load() {
		m.watchMu.Unlock()
		return
	}
	m.watched.Store(false)
	w, quit := m.w, m.quit
	m.w, m.quit = nil, nil
	m.watchMu.Unlock()
	m.opts.logf("[userconfig] %s; config changes are now read when settings are read", reason)
	close(quit)
	w.Close()
}

// stopWatch closes the watcher and any armed timer without changing the
// mode, and returns the watcher's close error.
func (m *Manager) stopWatch() error {
	m.watchMu.Lock()
	w, quit, t := m.w, m.quit, m.timer
	m.w, m.quit, m.timer = nil, nil, nil
	m.watchMu.Unlock()
	if t != nil {
		t.Stop()
	}
	if w == nil {
		return nil
	}
	close(quit)
	return w.Close()
}
