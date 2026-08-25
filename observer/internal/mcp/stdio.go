package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"log"
	"sync"

	"github.com/signalfx/obstudio/observer/internal/store"
)

const (
	maxConcurrentStdioRequests = 32
	stdioServerBusyErrorCode   = -32000
)

// RunStdio runs the MCP server over stdin/stdout using newline-delimited
// JSON-RPC. It blocks until the input stream closes or the output stream fails.
func RunStdio(s *store.Store, in io.ReadCloser, out io.Writer, params ...any) {
	d := NewDispatcher(s, params...)
	scanner := bufio.NewScanner(in)
	scanner.Buffer(make([]byte, 0, 1024*1024), 1024*1024)
	enc := json.NewEncoder(out)
	var writeMu sync.Mutex
	var writeErr error
	encode := func(response jsonRPCResponse) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		if writeErr != nil {
			return writeErr
		}
		writeErr = enc.Encode(response)
		return writeErr
	}

	type pendingRequest struct {
		cancel context.CancelFunc
	}
	var pendingMu sync.Mutex
	pendingByID := make(map[string]*pendingRequest)
	active := make(map[*pendingRequest]struct{})
	transportFailed := false
	var requests sync.WaitGroup
	cancelPending := func(key string) {
		pendingMu.Lock()
		request := pendingByID[key]
		pendingMu.Unlock()
		if request != nil {
			request.cancel()
		}
	}
	cancelAll := func() {
		pendingMu.Lock()
		requests := make([]*pendingRequest, 0, len(active))
		for request := range active {
			requests = append(requests, request)
		}
		pendingMu.Unlock()
		for _, request := range requests {
			request.cancel()
		}
	}
	failTransport := func(err error) {
		pendingMu.Lock()
		if transportFailed {
			pendingMu.Unlock()
			return
		}
		transportFailed = true
		requests := make([]*pendingRequest, 0, len(active))
		for request := range active {
			requests = append(requests, request)
		}
		pendingMu.Unlock()

		log.Printf("[mcp/stdio] write error: %v", err)
		for _, request := range requests {
			request.cancel()
		}
		_ = in.Close()
	}
	isTransportFailed := func() bool {
		pendingMu.Lock()
		defer pendingMu.Unlock()
		return transportFailed
	}

	for scanner.Scan() {
		if isTransportFailed() {
			break
		}

		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var req jsonRPCRequest
		if err := json.Unmarshal(line, &req); err != nil {
			if err := encode(rpcError(nil, -32700, "Parse error")); err != nil {
				failTransport(err)
				requests.Wait()
				return
			}
			continue
		}
		if !validJSONRPCRequestID(req.ID) {
			if err := encode(rpcError(nil, -32600, "Invalid Request")); err != nil {
				failTransport(err)
				requests.Wait()
				return
			}
			continue
		}

		if req.Method == "notifications/cancelled" {
			if key, ok := canceledRequestKey(req.Params); ok {
				cancelPending(key)
			}
			continue
		}

		ctx, cancel := context.WithCancel(context.Background())
		request := &pendingRequest{cancel: cancel}
		key, tracked := jsonRPCRequestKey(req.ID)
		pendingMu.Lock()
		if transportFailed {
			pendingMu.Unlock()
			cancel()
			cancelAll()
			requests.Wait()
			return
		}
		if len(active) >= maxConcurrentStdioRequests {
			pendingMu.Unlock()
			cancel()
			if tracked {
				if err := encode(rpcError(req.ID, stdioServerBusyErrorCode, "Server busy")); err != nil {
					failTransport(err)
					requests.Wait()
					return
				}
			}
			continue
		}
		active[request] = struct{}{}
		if tracked {
			if prior := pendingByID[key]; prior != nil {
				prior.cancel()
			}
			pendingByID[key] = request
		}
		requests.Add(1)
		pendingMu.Unlock()

		go func() {
			defer requests.Done()
			defer cancel()
			defer func() {
				pendingMu.Lock()
				delete(active, request)
				if tracked && pendingByID[key] == request {
					delete(pendingByID, key)
				}
				pendingMu.Unlock()
			}()

			resp, handled := d.DispatchContext(ctx, req)
			if !handled {
				return
			}
			if err := encode(resp); err != nil {
				failTransport(err)
			}
		}()
	}

	if err := scanner.Err(); err != nil && !isTransportFailed() {
		log.Printf("[mcp/stdio] read error: %v", err)
	}
	cancelAll()
	requests.Wait()
}

func canceledRequestKey(params any) (string, bool) {
	values, ok := params.(map[string]any)
	if !ok {
		return "", false
	}
	return jsonRPCRequestKey(values["requestId"])
}

func jsonRPCRequestKey(id any) (string, bool) {
	if id == nil || !validJSONRPCRequestID(id) {
		return "", false
	}
	encoded, err := json.Marshal(id)
	if err != nil {
		return "", false
	}
	return string(encoded), true
}
