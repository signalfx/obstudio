package store

import (
	"strings"
	"time"
)

type agentSpanIdentity struct {
	traceID string
	spanID  string
}

// AddAgentSpansForConnection retains one copy of each valid trace/span pair
// received through an AO-bound route. Re-export updates that copy in place and
// transfers its ownership to the latest receipt, so closing an earlier
// connection cannot remove a replay received by the current connection.
//
// This is local retention only, not a delivery cache: callers must still forward
// every retry upstream. Ordinary AddSpansForConnection behavior is unchanged.
// Deduplication lasts only while the span remains in the bounded ring; malformed
// or zero identifiers are retained independently rather than silently collapsed.
func (s *Store) AddAgentSpansForConnection(connID string, spans []Span) {
	s.mu.Lock()
	reset := s.checkSessionReset()
	indexes := make(map[agentSpanIdentity]int, s.spans.size())
	start := 0
	if s.spans.count == s.spans.cap {
		start = s.spans.head
	}
	for i := 0; i < s.spans.count; i++ {
		index := (start + i) % s.spans.cap
		if s.spans.items[index].agentReceipt {
			key, valid := agentSpanKey(s.spans.items[index])
			if valid {
				indexes[key] = index
			}
		}
	}
	for i := range spans {
		s.spanIngestRevision++
		spans[i].ingestRevision = s.spanIngestRevision
		spans[i].agentReceipt = true
		// Empty means the latest receipt is unowned, not owned by a stale peer.
		spans[i].ownerConnID = connID
		key, valid := agentSpanKey(spans[i])
		if index, exists := indexes[key]; valid && exists {
			s.spans.items[index] = spans[i]
			continue
		}
		index := s.spans.head
		if s.spans.count == s.spans.cap {
			if s.spans.items[index].agentReceipt {
				if evicted, ok := agentSpanKey(s.spans.items[index]); ok && indexes[evicted] == index {
					delete(indexes, evicted)
				}
			}
		}
		s.spans.push(spans[i : i+1])
		if valid {
			indexes[key] = index
		}
	}
	s.captureProviderTraceSpans(spans)
	s.captureCompletedProviderTasks(spans)
	changedAt := time.Now()
	s.lastIngest = changedAt
	s.mu.Unlock()
	if reset {
		s.runInvalidateCallback()
	}
	s.runChangeCallback(changedAt)
	if reset {
		s.notify(SignalTraces)
		s.notify(SignalMetrics)
		s.notify(SignalLogs)
		return
	}
	s.notify(SignalTraces)
}

func agentSpanKey(span Span) (agentSpanIdentity, bool) {
	if !validAgentSpanID(span.TraceID, 32) || !validAgentSpanID(span.SpanID, 16) {
		return agentSpanIdentity{}, false
	}
	return agentSpanIdentity{strings.ToLower(span.TraceID), strings.ToLower(span.SpanID)}, true
}

func validAgentSpanID(identifier string, length int) bool {
	if len(identifier) != length {
		return false
	}
	nonzero := false
	for i := range identifier {
		c := identifier[i]
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F') {
			return false
		}
		nonzero = nonzero || c != '0'
	}
	return nonzero
}
