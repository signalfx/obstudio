package mcp

import (
	"bufio"
	"encoding/json"
	"io"
	"log"

	"github.com/signalfx/obstudio/observer/internal/store"
)

// RunStdio runs the MCP server over stdin/stdout using newline-delimited
// JSON-RPC. It blocks until the input stream closes.
func RunStdio(s *store.Store, in io.Reader, out io.Writer) {
	d := NewDispatcher(s)
	scanner := bufio.NewScanner(in)
	scanner.Buffer(make([]byte, 0, 1024*1024), 1024*1024)
	enc := json.NewEncoder(out)

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var req jsonRPCRequest
		if err := json.Unmarshal(line, &req); err != nil {
			if err := enc.Encode(rpcError(nil, -32700, "Parse error")); err != nil {
				log.Printf("[mcp/stdio] write error: %v", err)
				return
			}
			continue
		}

		resp, handled := d.Dispatch(req)
		if !handled {
			continue
		}

		if err := enc.Encode(resp); err != nil {
			log.Printf("[mcp/stdio] write error: %v", err)
			return
		}
	}
}
