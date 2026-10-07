package store

import (
	"strings"
	"time"
)

type agentSpanIdentity struct {
	route   AgentSpanRoute
	traceID string
	spanID  string
}

// AgentSpanRoute identifies the AO destination for local retry retention.
type AgentSpanRoute struct {
	ProjectID string
	StreamID  string
}

// AddAgentSpansForConnection retains one copy of each valid route/trace/span
// identity received through an AO-bound route. Re-export updates that copy in place and
// transfers its ownership to the latest receipt, so closing an earlier
// connection cannot remove a replay received by the current connection.
//
// This is local retention only, not a delivery cache: callers must still forward
// every retry upstream. Ordinary AddSpansForConnection behavior is unchanged.
// Deduplication lasts only while the span remains in the bounded ring; malformed
// or zero identifiers are retained independently rather than silently collapsed.
func (s *Store) AddAgentSpansForConnection(connID string, route AgentSpanRoute, spans []Span) {
	s.mu.Lock()
	reset := s.checkSessionReset()
	route.ProjectID = strings.ToLower(route.ProjectID)
	route.StreamID = strings.ToLower(route.StreamID)
	for i := range spans {
		s.spanIngestRevision++
		spans[i].ingestRevision = s.spanIngestRevision
		spans[i].agentReceipt = true
		spans[i].agentRoute = route
		// Empty means the latest receipt is unowned, not owned by a stale peer.
		spans[i].ownerConnID = connID
		key, valid := agentSpanKey(spans[i])
		if index, exists := s.agentSpanIndex[key]; valid && exists {
			s.spans.items[index] = spans[i]
			continue
		}
		s.pushSpanWithAgentIndex(spans[i])
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

// pushSpanWithAgentIndex keeps AO retry identity aligned with physical ring
// overwrites. Callers hold s.mu; ordinary OTLP spans are never deduplicated.
func (s *Store) pushSpanWithAgentIndex(span Span) {
	index := s.spans.head
	if s.spans.count == s.spans.cap {
		if evicted := s.spans.items[index]; evicted.agentReceipt {
			if key, valid := agentSpanKey(evicted); valid && s.agentSpanIndex[key] == index {
				delete(s.agentSpanIndex, key)
			}
		}
	}
	s.spans.items[index] = span
	s.spans.head = (index + 1) % s.spans.cap
	if s.spans.count < s.spans.cap {
		s.spans.count++
	}
	if span.agentReceipt {
		if key, valid := agentSpanKey(span); valid {
			s.agentSpanIndex[key] = index
		}
	}
}

// rebuildAgentSpanIndex is only needed when connection eviction compacts the
// ring. It is not on the per-request ingest path.
func (s *Store) rebuildAgentSpanIndex() {
	clear(s.agentSpanIndex)
	start := 0
	if s.spans.count == s.spans.cap {
		start = s.spans.head
	}
	for i := 0; i < s.spans.count; i++ {
		index := (start + i) % s.spans.cap
		if span := s.spans.items[index]; span.agentReceipt {
			if key, valid := agentSpanKey(span); valid {
				s.agentSpanIndex[key] = index
			}
		}
	}
}

func agentSpanKey(span Span) (agentSpanIdentity, bool) {
	if !validAgentSpanID(span.TraceID, 32) || !validAgentSpanID(span.SpanID, 16) {
		return agentSpanIdentity{}, false
	}
	return agentSpanIdentity{span.agentRoute, strings.ToLower(span.TraceID), strings.ToLower(span.SpanID)}, true
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
