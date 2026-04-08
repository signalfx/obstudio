//go:build !windows

package otlp

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
)

// lsofRecord represents a parsed record from lsof -Fpcn output.
type lsofRecord struct {
	pid  int
	name string
}

// findOriginatingPID uses lsof to determine the PID of the process that
// owns the remote end of the given socket connection. This lets us detect
// when an instrumented application exits.
func findOriginatingPID(st socketTuple) (int, error) {
	out, err := exec.Command("lsof",
		"-nP",
		fmt.Sprintf("-iTCP:%d", st.remotePort),
		"-sTCP:ESTABLISHED",
		"-Fpcn",
	).Output()
	if err != nil {
		return 0, fmt.Errorf("lsof: %w", err)
	}

	records := parseLsofOutput(string(out))
	for _, rec := range records {
		if rec.pid == 0 || rec.name == "" {
			continue
		}
		connTuple := parseConnectionName(rec.name)
		if connTuple == nil {
			continue
		}
		// lsof reports from the remote process's perspective, so its
		// local address = our remote address and vice-versa.
		if connTuple.localAddr == st.remoteAddr &&
			connTuple.localPort == st.remotePort &&
			connTuple.remoteAddr == st.localAddr &&
			connTuple.remotePort == st.localPort {
			return rec.pid, nil
		}
	}
	return 0, fmt.Errorf("no matching lsof record for %s:%d->%s:%d",
		st.localAddr, st.localPort, st.remoteAddr, st.remotePort)
}

// parseLsofOutput parses the -Fpcn format where each field is prefixed with
// a single-character tag: p=PID, c=command, n=name.
func parseLsofOutput(output string) []lsofRecord {
	lines := strings.Split(output, "\n")
	var records []lsofRecord
	var current lsofRecord

	for _, line := range lines {
		if line == "" {
			continue
		}
		prefix := line[0]
		value := line[1:]

		switch prefix {
		case 'p':
			if current.pid != 0 || current.name != "" {
				records = append(records, current)
			}
			pid, _ := strconv.Atoi(value)
			current = lsofRecord{pid: pid}
		case 'n':
			current.name = value
		}
	}
	if current.pid != 0 || current.name != "" {
		records = append(records, current)
	}
	return records
}

// parseConnectionName parses an lsof connection name like
// "127.0.0.1:4318->127.0.0.1:54321" into a socketTuple.
func parseConnectionName(name string) *socketTuple {
	parts := strings.SplitN(name, "->", 2)
	if len(parts) != 2 {
		return nil
	}
	local := parseEndpoint(parts[0])
	remote := parseEndpoint(parts[1])
	if local == nil || remote == nil {
		return nil
	}
	return &socketTuple{
		localAddr:  local.addr,
		localPort:  local.port,
		remoteAddr: remote.addr,
		remotePort: remote.port,
	}
}

type endpoint struct {
	addr string
	port int
}

func parseEndpoint(s string) *endpoint {
	s = strings.TrimSpace(s)
	// Handle IPv6 [addr]:port format.
	if strings.HasPrefix(s, "[") {
		idx := strings.LastIndex(s, "]:")
		if idx < 0 {
			return nil
		}
		addr := normalizeLoopback(s[1:idx])
		port, err := strconv.Atoi(s[idx+2:])
		if err != nil {
			return nil
		}
		return &endpoint{addr: addr, port: port}
	}
	// IPv4 addr:port — use last colon to handle edge cases.
	idx := strings.LastIndex(s, ":")
	if idx < 0 {
		return nil
	}
	addr := normalizeLoopback(s[:idx])
	port, err := strconv.Atoi(s[idx+1:])
	if err != nil {
		return nil
	}
	return &endpoint{addr: addr, port: port}
}

// processAlive checks whether a process with the given PID exists using
// the kill(pid, 0) system call. Returns true if the process exists (even
// if we don't have permission to signal it).
func processAlive(pid int) bool {
	err := syscall.Kill(pid, 0)
	if err == nil {
		return true
	}
	// EPERM means the process exists but we don't have permission.
	return err == syscall.EPERM
}
