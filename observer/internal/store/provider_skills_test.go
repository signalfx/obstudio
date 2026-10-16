package store

import (
	"sync"
	"testing"
	"time"
)

func TestProviderSkillActivationsRetainSourceIdentityWithoutInventingCompletion(t *testing.T) {
	s := New()
	s.providerSkillActivations = newRingBuffer[ProviderSkillActivation](2)
	record := LogRecord{Timestamp: time.Now(), Body: "claude_code.skill_activated", Attributes: map[string]any{
		"skill.name": "audit", "session.id": "session", "event.sequence": int64(1), "invocation_trigger": "user-slash",
	}}
	s.AddLogsForConnection("host", []LogRecord{record, record})
	if got := s.SnapshotProviderSkillActivations(); len(got) != 1 || got[0].Coverage != "native_activation" || got[0].Trigger != "user-slash" {
		t.Fatalf("native retransmission: %+v", got)
	}
	s.EvictConnection("host")
	if len(s.SnapshotProviderSkillActivations()) != 1 {
		t.Fatal("activation lost on disconnect")
	}
	for i := int64(2); i <= 3; i++ {
		next := record
		next.Attributes = map[string]any{"skill.name": "audit", "session.id": "session", "event.sequence": i}
		s.AddLogsForConnection("host", []LogRecord{next})
	}
	if len(s.SnapshotProviderSkillActivations()) != 2 || len(s.providerSkillKeys) != 2 {
		t.Fatal("retention or dedupe keys unbounded")
	}
	s.Clear()
	if len(s.SnapshotProviderSkillActivations()) != 0 || len(s.providerSkillKeys) != 0 {
		t.Fatal("clear retained activations")
	}
	delete(record.Attributes, "event.sequence")
	s.AddLogsForConnection("host", []LogRecord{record, record})
	if got := s.SnapshotProviderSkillActivations(); len(got) != 2 || got[0].Coverage != "identity_unavailable" {
		t.Fatalf("invented identity: %+v", got)
	}
}

func TestProviderSkillObservationsIsolateConcurrentIngestion(t *testing.T) {
	s := New()
	var workers sync.WaitGroup
	for i := 0; i < 8; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			s.AddLogsForConnection("host", []LogRecord{{Body: "unrelated", Attributes: map[string]any{"skill.name": "ignore"}}})
			s.AddMetricsForConnection("host", []MetricDataPoint{{Name: "codex.skill.injected", Type: "sum", IsMonotonic: true, Value: 1, Attributes: map[string]any{"skill": "audit", "status": "ok"}}})
			_ = s.SnapshotProviderSkillInjections()
		}()
	}
	workers.Wait()
	if len(s.SnapshotProviderSkillActivations()) != 0 || len(s.SnapshotProviderSkillInjections()) != 8 {
		t.Fatal("mixed provider observations corrupted")
	}
}
