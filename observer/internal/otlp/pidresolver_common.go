package otlp

import (
	"fmt"
	"net"
	"strings"
)

// socketTuple identifies a TCP connection by both endpoints.
type socketTuple struct {
	localAddr  string
	localPort  int
	remoteAddr string
	remotePort int
}

// normalizeLoopback strips IPv4-mapped IPv6 prefixes (::ffff:) and normalizes
// common loopback representations.
func normalizeLoopback(addr string) string {
	if strings.HasPrefix(addr, "::ffff:") {
		addr = addr[len("::ffff:"):]
	}
	return addr
}

// socketTupleFromConn extracts the socket tuple from a net.Conn.
func socketTupleFromConn(conn net.Conn) *socketTuple {
	local, ok := conn.LocalAddr().(*net.TCPAddr)
	if !ok {
		return nil
	}
	remote, ok := conn.RemoteAddr().(*net.TCPAddr)
	if !ok {
		return nil
	}
	return &socketTuple{
		localAddr:  normalizeLoopback(local.IP.String()),
		localPort:  local.Port,
		remoteAddr: normalizeLoopback(remote.IP.String()),
		remotePort: remote.Port,
	}
}

// addressKey returns a string key for deduplicating connections by socket tuple.
func (st *socketTuple) addressKey() string {
	return fmt.Sprintf("%s|%d|%s|%d", st.remoteAddr, st.remotePort, st.localAddr, st.localPort)
}
