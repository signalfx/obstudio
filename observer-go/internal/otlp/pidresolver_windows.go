//go:build windows

package otlp

import (
	"encoding/binary"
	"fmt"
	"math/bits"
	"net"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	modiphlpapi             = windows.NewLazySystemDLL("iphlpapi.dll")
	procGetExtendedTcpTable = modiphlpapi.NewProc("GetExtendedTcpTable")
)

const (
	tcpTableOwnerPIDConnections = 4
	noError                     = 0
)

type mibTCPRowOwnerPID struct {
	State      uint32
	LocalAddr  uint32
	LocalPort  uint32
	RemoteAddr uint32
	RemotePort uint32
	OwningPID  uint32
}

type mibTCP6RowOwnerPID struct {
	LocalAddr     [16]byte
	LocalScopeID  uint32
	LocalPort     uint32
	RemoteAddr    [16]byte
	RemoteScopeID uint32
	RemotePort    uint32
	State         uint32
	OwningPID     uint32
}

// findOriginatingPID uses GetExtendedTcpTable to determine the PID of the
// process that owns the remote end of the given socket connection.
func findOriginatingPID(st socketTuple) (int, error) {
	if pid, err := findOriginatingPIDIPv4(st); err == nil {
		return pid, nil
	}
	if pid, err := findOriginatingPIDIPv6(st); err == nil {
		return pid, nil
	}
	return 0, fmt.Errorf("no matching TCP owner PID for %s:%d->%s:%d",
		st.localAddr, st.localPort, st.remoteAddr, st.remotePort)
}

func findOriginatingPIDIPv4(st socketTuple) (int, error) {
	rows, err := getExtendedTCPRowsIPv4()
	if err != nil {
		return 0, err
	}
	for _, row := range rows {
		if row.State == 0 {
			continue
		}
		if ipv4String(row.LocalAddr) == st.remoteAddr &&
			portFromDWORD(row.LocalPort) == st.remotePort &&
			ipv4String(row.RemoteAddr) == st.localAddr &&
			portFromDWORD(row.RemotePort) == st.localPort {
			return int(row.OwningPID), nil
		}
	}
	return 0, fmt.Errorf("no matching IPv4 TCP row")
}

func findOriginatingPIDIPv6(st socketTuple) (int, error) {
	rows, err := getExtendedTCPRowsIPv6()
	if err != nil {
		return 0, err
	}
	for _, row := range rows {
		if row.State == 0 {
			continue
		}
		if normalizeLoopback(net.IP(row.LocalAddr[:]).String()) == st.remoteAddr &&
			portFromDWORD(row.LocalPort) == st.remotePort &&
			normalizeLoopback(net.IP(row.RemoteAddr[:]).String()) == st.localAddr &&
			portFromDWORD(row.RemotePort) == st.localPort {
			return int(row.OwningPID), nil
		}
	}
	return 0, fmt.Errorf("no matching IPv6 TCP row")
}

func getExtendedTCPRowsIPv4() ([]mibTCPRowOwnerPID, error) {
	buf, err := getExtendedTCPTable(windows.AF_INET)
	if err != nil {
		return nil, err
	}
	return decodeTableRows[mibTCPRowOwnerPID](buf), nil
}

func getExtendedTCPRowsIPv6() ([]mibTCP6RowOwnerPID, error) {
	buf, err := getExtendedTCPTable(windows.AF_INET6)
	if err != nil {
		return nil, err
	}
	return decodeTableRows[mibTCP6RowOwnerPID](buf), nil
}

func getExtendedTCPTable(addressFamily uint32) ([]byte, error) {
	var size uint32
	r1, _, _ := procGetExtendedTcpTable.Call(
		0,
		uintptr(unsafe.Pointer(&size)),
		0,
		uintptr(addressFamily),
		uintptr(tcpTableOwnerPIDConnections),
		0,
	)
	if r1 != uintptr(windows.ERROR_INSUFFICIENT_BUFFER) && r1 != noError {
		return nil, windows.Errno(r1)
	}

	buf := make([]byte, size)
	r1, _, _ = procGetExtendedTcpTable.Call(
		uintptr(unsafe.Pointer(&buf[0])),
		uintptr(unsafe.Pointer(&size)),
		0,
		uintptr(addressFamily),
		uintptr(tcpTableOwnerPIDConnections),
		0,
	)
	if r1 != noError {
		return nil, windows.Errno(r1)
	}
	return buf, nil
}

func decodeTableRows[T any](buf []byte) []T {
	if len(buf) < 4 {
		return nil
	}
	rowCount := int(binary.LittleEndian.Uint32(buf[:4]))
	if rowCount == 0 {
		return nil
	}
	rowSize := int(unsafe.Sizeof(*new(T)))
	rowAlign := int(unsafe.Alignof(*new(T)))
	rowOffset := alignUp(4, rowAlign)
	maxRows := (len(buf) - rowOffset) / rowSize
	if maxRows < 0 {
		return nil
	}
	if rowCount > maxRows {
		rowCount = maxRows
	}
	if rowCount <= 0 {
		return nil
	}
	return unsafe.Slice((*T)(unsafe.Pointer(&buf[rowOffset])), rowCount)
}

func alignUp(v, alignment int) int {
	if alignment <= 1 {
		return v
	}
	mask := alignment - 1
	return (v + mask) &^ mask
}

func ipv4String(addr uint32) string {
	ip := net.IPv4(byte(addr), byte(addr>>8), byte(addr>>16), byte(addr>>24))
	return normalizeLoopback(ip.String())
}

func portFromDWORD(v uint32) int {
	return int(bits.ReverseBytes16(uint16(v)))
}

// processAlive checks whether a process with the given PID exists by opening a
// process handle and waiting with a zero timeout.
func processAlive(pid int) bool {
	handle, err := windows.OpenProcess(windows.SYNCHRONIZE|windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return err == windows.ERROR_ACCESS_DENIED
	}
	defer windows.CloseHandle(handle)

	event, err := windows.WaitForSingleObject(handle, 0)
	if err != nil {
		return false
	}
	return event == uint32(windows.WAIT_TIMEOUT)
}
