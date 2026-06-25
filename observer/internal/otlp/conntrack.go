package otlp

import (
	"context"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/stats"
)

// ConnTracker wraps the OTLP receiver with proxies that provide disconnect
// detection so the UI clears immediately when the instrumented app exits.
//
// Two transport-specific strategies are used:
//
//   - gRPC: connection-aware proxy. gRPC/HTTP2 connections are long-lived.
//     When a connection closes, that connection's data is evicted from the
//     store after a short debounce (for restart reconnects).
//
//   - HTTP: PID-based process monitoring. On the first HTTP request from a
//     new socket, platform-specific code resolves the remote process PID.
//     A background goroutine polls process liveness every second. When the
//     process exits, that connection's data is evicted from the store.
type ConnTracker struct {
	store          *store.Store
	grpcServer     *grpc.Server
	httpServer     *http.Server
	grpcLn         net.Listener
	httpLn         net.Listener
	backendCC      *grpc.ClientConn
	exporter       MetricsExporter
	tracesExporter TracesExporter

	mu sync.Mutex

	// gRPC connection tracking
	grpcConns map[string]struct{} // connID → exists

	// HTTP PID-based tracking
	httpConnsByAddr map[string]*httpConn    // addressKey → conn
	httpConnsByID   map[string]*httpConn    // connID → conn
	pidWatchers     map[int]chan struct{}   // pid → stop channel
	pidConns        map[int]map[string]bool // pid → set of connIDs
	nextHTTPConnID  int

	stop chan struct{} // closed on shutdown
}

// httpConn tracks a single HTTP connection's PID.
// This is unexported and for internal use only.
type httpConn struct {
	connID     string
	addressKey string
	pid        int
}

const grpcConnIDMetadataKey = "x-obstudio-conn-id"

// StartConnTracker creates a gRPC proxy and an HTTP OTLP handler with connection tracking.
// The gRPC proxy tracks connections for disconnect detection.
// The HTTP handler resolves PIDs and monitors process liveness.
// internalGRPCAddr is where the internal gRPC receiver listens.
func StartConnTracker(
	s *store.Store,
	grpcAddr, httpAddr string,
	internalGRPCAddr string,
	exporter MetricsExporter,
	tracesExporter TracesExporter,
) (*ConnTracker, error) {
	ct := &ConnTracker{
		store:           s,
		exporter:        exporter,
		tracesExporter:  tracesExporter,
		grpcConns:       make(map[string]struct{}),
		httpConnsByAddr: make(map[string]*httpConn),
		httpConnsByID:   make(map[string]*httpConn),
		pidWatchers:     make(map[int]chan struct{}),
		pidConns:        make(map[int]map[string]bool),
		stop:            make(chan struct{}),
	}

	if err := ct.startGRPCProxy(grpcAddr, internalGRPCAddr); err != nil {
		return nil, fmt.Errorf("grpc proxy: %w", err)
	}

	if err := ct.startHTTPHandler(httpAddr); err != nil {
		ct.grpcServer.Stop()
		ct.grpcLn.Close()
		ct.backendCC.Close()
		return nil, fmt.Errorf("http handler: %w", err)
	}

	return ct, nil
}

// Shutdown stops both proxies gracefully and closes all watchers.
func (ct *ConnTracker) Shutdown() {
	close(ct.stop)

	ct.mu.Lock()
	// Stop all PID watchers.
	for _, stopCh := range ct.pidWatchers {
		close(stopCh)
	}
	ct.pidWatchers = make(map[int]chan struct{})
	ct.mu.Unlock()

	ct.grpcServer.GracefulStop()
	if ct.backendCC != nil {
		ct.backendCC.Close()
	}
	if ct.httpServer != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		ct.httpServer.Shutdown(ctx)
	}
}

// --- HTTP PID-based tracking ---

// resolveHTTPConnection extracts the socket tuple from an HTTP request,
// resolves the remote PID, and starts a PID watcher if needed.
// Returns the connection ID for store segregation.
func (ct *ConnTracker) resolveHTTPConnection(conn net.Conn) string {
	st := socketTupleFromConn(conn)
	if st == nil {
		return ""
	}

	addrKey := st.addressKey()

	ct.mu.Lock()
	// Already tracked this socket?
	if existing, ok := ct.httpConnsByAddr[addrKey]; ok {
		ct.mu.Unlock()
		return existing.connID
	}
	ct.mu.Unlock()

	// Resolve PID using the platform-specific socket ownership lookup.
	pid, err := findOriginatingPID(*st)
	if err != nil {
		log.Printf("[conntrack] could not resolve PID for %s: %v", addrKey, err)
		return ""
	}

	ct.mu.Lock()
	defer ct.mu.Unlock()

	// Check again after acquiring lock (another request may have resolved it).
	if existing, ok := ct.httpConnsByAddr[addrKey]; ok {
		return existing.connID
	}

	ct.nextHTTPConnID++
	connID := fmt.Sprintf("http-%d-pid-%d", ct.nextHTTPConnID, pid)
	hc := &httpConn{connID: connID, addressKey: addrKey, pid: pid}
	ct.httpConnsByAddr[addrKey] = hc
	ct.httpConnsByID[connID] = hc

	if ct.pidConns[pid] == nil {
		ct.pidConns[pid] = make(map[string]bool)
	}
	ct.pidConns[pid][connID] = true

	ct.ensurePIDWatcherLocked(pid)

	log.Printf("[conntrack] tracked HTTP connection %s (pid %d)", connID, pid)
	return connID
}

// ensurePIDWatcherLocked starts a background goroutine that polls kill(pid, 0)
// every second. When the process exits, all its connections are evicted.
// Must be called with ct.mu held.
func (ct *ConnTracker) ensurePIDWatcherLocked(pid int) {
	if _, ok := ct.pidWatchers[pid]; ok {
		return
	}

	stopCh := make(chan struct{})
	ct.pidWatchers[pid] = stopCh

	go func() {
		ticker := time.NewTicker(1 * time.Second)
		defer ticker.Stop()

		for {
			select {
			case <-stopCh:
				return
			case <-ct.stop:
				return
			case <-ticker.C:
				if processAlive(pid) {
					continue
				}

				log.Printf("[conntrack] process %d exited, evicting connections", pid)
				ct.evictPID(pid)
				return
			}
		}
	}()
}

// evictPID removes all connections associated with a PID and evicts their
// data from the store.
func (ct *ConnTracker) evictPID(pid int) {
	ct.mu.Lock()
	connIDs := ct.pidConns[pid]
	delete(ct.pidConns, pid)
	if stopCh, ok := ct.pidWatchers[pid]; ok {
		// Stop channel may already be closed during shutdown — guard with select.
		select {
		case <-stopCh:
		default:
			close(stopCh)
		}
		delete(ct.pidWatchers, pid)
	}

	for connID := range connIDs {
		if hc, ok := ct.httpConnsByID[connID]; ok {
			delete(ct.httpConnsByAddr, hc.addressKey)
			delete(ct.httpConnsByID, connID)
		}
	}
	ct.mu.Unlock()

	// Evict data outside the lock.
	for connID := range connIDs {
		log.Printf("[conntrack] evicting HTTP connection %s (pid-exit:%d)", connID, pid)
		ct.store.EvictConnection(connID)
	}
}

// --- gRPC connection tracking ---

func (ct *ConnTracker) addGRPCConn(id string) {
	ct.mu.Lock()
	defer ct.mu.Unlock()
	ct.grpcConns[id] = struct{}{}
}

func (ct *ConnTracker) removeGRPCConn(id string) {
	ct.mu.Lock()
	_, existed := ct.grpcConns[id]
	delete(ct.grpcConns, id)
	ct.mu.Unlock()

	if !existed {
		return
	}

	log.Printf("[conntrack] gRPC connection %s closed, evicting its telemetry", id)
	ct.store.EvictConnection(id)
}

// --- gRPC proxy ---

func (ct *ConnTracker) startGRPCProxy(listenAddr, backendAddr string) error {
	ln, err := net.Listen("tcp", listenAddr)
	if err != nil {
		return fmt.Errorf("listen %s: %w", listenAddr, err)
	}
	ct.grpcLn = ln

	backendConn, err := grpc.NewClient(
		backendAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		ln.Close()
		return fmt.Errorf("dial backend %s: %w", backendAddr, err)
	}
	ct.backendCC = backendConn

	ct.grpcServer = grpc.NewServer(
		grpc.StatsHandler(&grpcConnHandler{ct: ct}),
		grpc.UnknownServiceHandler(newStreamForwarder(backendConn)),
	)

	go ct.grpcServer.Serve(ln)
	return nil
}

// grpcConnHandler implements [stats.Handler] to track gRPC connection
// lifecycle events.
type grpcConnHandler struct {
	ct *ConnTracker
}

type ctxKeyConnID struct{}

func (h *grpcConnHandler) TagRPC(ctx context.Context, _ *stats.RPCTagInfo) context.Context {
	return ctx
}

func (h *grpcConnHandler) HandleRPC(_ context.Context, _ stats.RPCStats) {}

func (h *grpcConnHandler) TagConn(ctx context.Context, info *stats.ConnTagInfo) context.Context {
	connID := fmt.Sprintf("grpc-%s", info.RemoteAddr.String())
	h.ct.addGRPCConn(connID)
	return context.WithValue(ctx, ctxKeyConnID{}, connID)
}

func (h *grpcConnHandler) HandleConn(ctx context.Context, s stats.ConnStats) {
	if _, ok := s.(*stats.ConnEnd); ok {
		if connID, ok := ctx.Value(ctxKeyConnID{}).(string); ok {
			h.ct.removeGRPCConn(connID)
		}
	}
}

// newStreamForwarder returns a [grpc.StreamHandler] that transparently
// proxies all RPCs to the backend connection without deserialization.
func newStreamForwarder(backend *grpc.ClientConn) grpc.StreamHandler {
	return func(_ any, serverStream grpc.ServerStream) error {
		method, ok := grpc.Method(serverStream.Context())
		if !ok {
			return fmt.Errorf("cannot determine gRPC method from stream context")
		}

		ctx := serverStream.Context()
		if connID := grpcConnIDFromContext(ctx); connID != "" {
			ctx = metadata.AppendToOutgoingContext(ctx, grpcConnIDMetadataKey, connID)
		}

		clientStream, err := backend.NewStream(
			ctx,
			&grpc.StreamDesc{ServerStreams: true, ClientStreams: true},
			method,
		)
		if err != nil {
			return err
		}

		errCh := make(chan error, 2)

		// client → backend: forward request frames.
		go func() {
			for {
				msg := &rawFrame{}
				if err := serverStream.RecvMsg(msg); err != nil {
					clientStream.CloseSend()
					if err == io.EOF {
						errCh <- nil
					} else {
						errCh <- err
					}
					return
				}
				if err := clientStream.SendMsg(msg); err != nil {
					errCh <- err
					return
				}
			}
		}()

		// backend → client: forward response frames.
		go func() {
			for {
				msg := &rawFrame{}
				if err := clientStream.RecvMsg(msg); err != nil {
					if err == io.EOF {
						errCh <- nil
					} else {
						errCh <- err
					}
					return
				}
				if err := serverStream.SendMsg(msg); err != nil {
					errCh <- err
					return
				}
			}
		}()

		// Wait for both goroutines. Return the first real error, if any.
		var firstErr error
		for i := 0; i < 2; i++ {
			if err := <-errCh; err != nil && firstErr == nil {
				firstErr = err
			}
		}
		return firstErr
	}
}

func grpcConnIDFromContext(ctx context.Context) string {
	if p, ok := peer.FromContext(ctx); ok && p.Addr != nil {
		return fmt.Sprintf("grpc-%s", p.Addr.String())
	}
	return ""
}

// rawFrame passes raw gRPC bytes through without deserializing.
type rawFrame struct {
	data []byte
}

func (f *rawFrame) Marshal() ([]byte, error) { return f.data, nil }
func (f *rawFrame) Unmarshal(b []byte) error { f.data = b; return nil }
func (f *rawFrame) ProtoMessage()            {}
func (f *rawFrame) Reset()                   {}
func (f *rawFrame) String() string           { return string(f.data) }

// --- HTTP OTLP handler (direct, no proxy) ---

type ctxKeyRawConn struct{}

// startHTTPHandler creates an HTTP server that handles OTLP/HTTP requests
// directly (instead of proxying to an internal receiver). This lets us
// resolve the PID from the connection and tag data with the connection ID.
func (ct *ConnTracker) startHTTPHandler(listenAddr string) error {
	handler := &otlpHTTPHandler{store: ct.store, ct: ct, exporter: ct.exporter, tracesExporter: ct.tracesExporter}

	ln, err := net.Listen("tcp", listenAddr)
	if err != nil {
		return fmt.Errorf("listen %s: %w", listenAddr, err)
	}
	ct.httpLn = ln

	ct.httpServer = &http.Server{
		Handler: handler,
		ConnContext: func(ctx context.Context, c net.Conn) context.Context {
			return context.WithValue(ctx, ctxKeyRawConn{}, c)
		},
	}

	go ct.httpServer.Serve(ln)
	return nil
}

// resolveHTTPConnectionFromRequest extracts the underlying net.Conn from the
// request context, resolves the PID, and returns the connection ID.
func (ct *ConnTracker) resolveHTTPConnectionFromRequest(r *http.Request) string {
	conn, ok := r.Context().Value(ctxKeyRawConn{}).(net.Conn)
	if !ok {
		return ""
	}
	return ct.resolveHTTPConnection(conn)
}
