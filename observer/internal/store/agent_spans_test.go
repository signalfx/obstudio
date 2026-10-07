package store

import (
	"fmt"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

func testAgentStoredSpan(traceID, spanID int) Span {
	return newTestSpan(fmt.Sprintf("%032x", traceID), fmt.Sprintf("%016x", spanID), "chat fixture-model", time.Now(), 1)
}

func TestAddAgentSpansDeduplicatesRetriesAndRetainsDistinctIDs(t *testing.T) {
	s := New()
	span := testAgentStoredSpan(1, 1)
	span.Attributes = map[string]any{"gen_ai.operation.name": "chat", "metadata-only": true}
	span.Events = []SpanEvent{{Name: "safe-event", Attributes: map[string]any{"outcome": "success"}}}
	span.Links = []SpanLink{{TraceID: fmt.Sprintf("%032x", 2), SpanID: fmt.Sprintf("%016x", 1)}}
	for range 4 {
		s.AddAgentSpansForConnection("current", []Span{span, span})
	}
	if s.Stats().SpanCount != 1 {
		t.Fatalf("local retry count = %d, want 1", s.Stats().SpanCount)
	}
	retained := s.SnapshotSpans()[0]
	if !reflect.DeepEqual(retained.Attributes, span.Attributes) || !reflect.DeepEqual(retained.Events, span.Events) ||
		!reflect.DeepEqual(retained.Links, span.Links) || retained.StartTime != span.StartTime || retained.EndTime != span.EndTime {
		t.Fatal("local dedup changed span content, privacy metadata, links, or times")
	}
	s.AddAgentSpansForConnection("current", []Span{testAgentStoredSpan(1, 2), testAgentStoredSpan(2, 1)})
	if s.Stats().SpanCount != 3 {
		t.Fatalf("distinct trace/span IDs were collapsed: %d", s.Stats().SpanCount)
	}
	if trace := s.Trace(span.TraceID, 10); trace == nil || trace.SpanCount != 2 {
		t.Fatal("trace queries did not reflect unique locally retained spans")
	}
}

func TestAddAgentSpansLatestReceiptOwnsReplay(t *testing.T) {
	for _, current := range []string{"new-connection", ""} {
		t.Run("owner="+current, func(t *testing.T) {
			s := New()
			span := testAgentStoredSpan(1, 1)
			s.AddAgentSpansForConnection("old-connection", []Span{span})
			span.Name = "chat latest-model"
			s.AddAgentSpansForConnection(current, []Span{span})
			s.EvictConnection("old-connection")
			retained := s.SnapshotSpans()
			if len(retained) != 1 || retained[0].ownerConnID != current || retained[0].Name != span.Name {
				t.Fatal("prior owner eviction removed or replaced the current receipt")
			}
			if current != "" {
				s.EvictConnection(current)
				if s.Stats().SpanCount != 0 {
					t.Fatal("latest owner eviction did not remove its retained copy")
				}
				s.AddAgentSpansForConnection("reconnected", []Span{span})
				if s.Stats().SpanCount != 1 {
					t.Fatal("reconnect was suppressed by stale dedup state")
				}
			}
		})
	}
}

func TestAddAgentSpansPreservesMalformedAndZeroIDs(t *testing.T) {
	cases := []Span{
		{TraceID: "", SpanID: ""},
		{TraceID: strings.Repeat("0", 32), SpanID: fmt.Sprintf("%016x", 1)},
		{TraceID: fmt.Sprintf("%032x", 1), SpanID: strings.Repeat("0", 16)},
		{TraceID: strings.Repeat("z", 32), SpanID: fmt.Sprintf("%016x", 1)},
		{TraceID: "trace-1", SpanID: "span-1"},
	}
	for _, span := range cases {
		s := New()
		s.AddAgentSpansForConnection("connection", []Span{span, span})
		if s.Stats().SpanCount != 2 {
			t.Fatal("malformed or zero identity silently collapsed")
		}
	}
	s := New()
	span := testAgentStoredSpan(10, 10)
	s.AddAgentSpansForConnection("connection", []Span{span})
	span.TraceID, span.SpanID = strings.ToUpper(span.TraceID), strings.ToUpper(span.SpanID)
	s.AddAgentSpansForConnection("connection", []Span{span})
	if s.Stats().SpanCount != 1 {
		t.Fatal("hex case changed the OTel identity")
	}
}

func TestAddAgentSpansClearSessionResetAndCapacityHaveNoStaleCache(t *testing.T) {
	for _, reset := range []string{"clear", "session", "capacity"} {
		t.Run(reset, func(t *testing.T) {
			s := New()
			s.spans = newRingBuffer[Span](2)
			span := testAgentStoredSpan(1, 1)
			s.AddAgentSpansForConnection("old", []Span{span})
			switch reset {
			case "clear":
				s.Clear()
			case "session":
				s.lastIngest = time.Now().Add(-time.Minute)
			case "capacity":
				s.AddAgentSpansForConnection("noise", []Span{testAgentStoredSpan(2, 1), testAgentStoredSpan(3, 1)})
			}
			s.AddAgentSpansForConnection("current", []Span{span})
			trace := s.Trace(span.TraceID, 10)
			if trace == nil || trace.SpanCount != 1 {
				t.Fatal("retention reset suppressed a fresh receipt")
			}
			if s.Stats().SpanCount > 2 {
				t.Fatal("dedup exceeded the local ring capacity")
			}
		})
	}
	// Wrap several times within one request: the transient index must follow
	// physical ring eviction rather than update an overwritten/stale slot.
	s := New()
	s.spans = newRingBuffer[Span](2)
	a, b, c := testAgentStoredSpan(1, 1), testAgentStoredSpan(2, 1), testAgentStoredSpan(3, 1)
	s.AddAgentSpansForConnection("connection", []Span{a, b, c, a, a})
	if s.Stats().SpanCount != 2 || s.Trace(a.TraceID, 10) == nil || s.Trace(c.TraceID, 10) == nil || s.Trace(b.TraceID, 10) != nil {
		t.Fatal("batch wrap reused a stale identity index")
	}
}

func TestAddAgentSpansDoesNotChangeOrdinaryStoreInsertion(t *testing.T) {
	s := New()
	span := testAgentStoredSpan(1, 1)
	s.AddSpansForConnection("ordinary", []Span{span, span})
	if s.Stats().SpanCount != 2 {
		t.Fatal("ordinary duplicate insertion behavior changed")
	}
	s.AddAgentSpansForConnection("agent", []Span{testAgentStoredSpan(2, 1), testAgentStoredSpan(2, 1)})
	if s.Stats().SpanCount != 3 {
		t.Fatal("AO dedup modified unrelated ordinary retained records")
	}
}

func TestAgentRetryDoesNotTransferOrdinarySpanOwnership(t *testing.T) {
	s := New()
	span := testAgentStoredSpan(1, 1)
	s.AddSpansForConnection("ordinary", []Span{span})
	s.AddAgentSpansForConnection("agent", []Span{span, span})
	if s.Stats().SpanCount != 2 {
		t.Fatalf("ordinary and AO receipts were not retained independently: %d", s.Stats().SpanCount)
	}
	s.EvictConnection("agent")
	retained := s.SnapshotSpans()
	if len(retained) != 1 || retained[0].ownerConnID != "ordinary" || retained[0].agentReceipt {
		t.Fatalf("AO disconnect removed the ordinary receipt: %+v", retained)
	}
	s.AddAgentSpansForConnection("reconnected", []Span{span, span})
	if s.Stats().SpanCount != 2 {
		t.Fatal("AO reconnect did not retain its route without replacing ordinary data")
	}
	s.EvictConnection("ordinary")
	retained = s.SnapshotSpans()
	if len(retained) != 1 || retained[0].ownerConnID != "reconnected" || !retained[0].agentReceipt {
		t.Fatalf("ordinary disconnect removed the AO receipt: %+v", retained)
	}
}

func TestAddAgentSpansConcurrentRetries(t *testing.T) {
	s := New()
	span := testAgentStoredSpan(1, 1)
	var workers sync.WaitGroup
	for worker := range 20 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for range 20 {
				s.AddAgentSpansForConnection(fmt.Sprint(worker), []Span{span})
			}
		}()
	}
	workers.Wait()
	s.AddAgentSpansForConnection("current", []Span{span})
	for worker := range 20 {
		s.EvictConnection(fmt.Sprint(worker))
	}
	if s.Stats().SpanCount != 1 || s.SnapshotSpans()[0].ownerConnID != "current" {
		t.Fatal("concurrent retries inflated storage or lost the current owner")
	}
}
