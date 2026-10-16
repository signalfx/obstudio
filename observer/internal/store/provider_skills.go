package store

import (
	"fmt"
	"math"
	"strings"
	"time"
)

const defaultProviderSkillCap = 1_000

// ProviderSkillActivation describes loading a skill, not completing its work.
type ProviderSkillActivation struct {
	Provider       string    `json:"provider"`
	SkillName      string    `json:"skillName"`
	Trigger        string    `json:"trigger,omitempty"`
	Source         string    `json:"source,omitempty"`
	ConversationID string    `json:"conversationId,omitempty"`
	TaskID         string    `json:"taskId,omitempty"`
	ServiceName    string    `json:"serviceName,omitempty"`
	HostVersion    string    `json:"hostVersion,omitempty"`
	Timestamp      time.Time `json:"timestamp"`
	Coverage       string    `json:"coverage"`
	dedupeKey      string
}

// ProviderSkillInjection preserves native aggregate injection evidence.
type ProviderSkillInjection struct {
	Provider    string    `json:"provider"`
	SkillName   string    `json:"skillName"`
	Status      string    `json:"injectionStatus"`
	Value       float64   `json:"value"`
	Temporality string    `json:"temporality"`
	Timestamp   time.Time `json:"timestamp"`
	ServiceName string    `json:"serviceName,omitempty"`
}

func providerSkillActivation(record LogRecord) (ProviderSkillActivation, bool) {
	event := normalizedProviderTelemetryString(record.Attributes["event.name"])
	if event != "skill_activated" && event != "claude_code.skill_activated" &&
		!strings.EqualFold(strings.TrimSpace(record.Body), "claude_code.skill_activated") {
		return ProviderSkillActivation{}, false
	}
	if event == "skill_activated" && !strings.EqualFold(strings.TrimSpace(record.Body), "claude_code.skill_activated") && !strings.Contains(strings.ToLower(record.Resource.ServiceName+" "+record.Scope.Name), "claude") {
		return ProviderSkillActivation{}, false
	}
	name := providerTelemetryAttributeString(record.Attributes, "skill.name")
	if name == "" {
		return ProviderSkillActivation{}, false
	}
	a := ProviderSkillActivation{
		Provider: "claude", SkillName: name,
		Trigger:        providerTelemetryAttributeString(record.Attributes, "invocation_trigger"),
		Source:         providerTelemetryAttributeString(record.Attributes, "skill.source"),
		ConversationID: providerTelemetryAttributeString(record.Attributes, "session.id"),
		TaskID:         providerTelemetryAttributeString(record.Attributes, "prompt.id"),
		Timestamp:      LogEventTimestamp(record),
		Coverage:       "identity_unavailable",
		ServiceName:    record.Resource.ServiceName,
		HostVersion:    providerTelemetryAttributeString(record.Resource.Attributes, "service.version"),
	}
	if a.ConversationID == "" {
		a.ConversationID = providerTelemetryAttributeString(record.Attributes, "conversation.id")
	}
	if a.TaskID == "" {
		a.TaskID = providerTelemetryAttributeString(record.Attributes, "turn.id")
	}
	sequence, hasSequence := record.Attributes["event.sequence"]
	switch value := sequence.(type) {
	case int64:
		hasSequence = value >= 0
	case float64:
		hasSequence = value >= 0 && !math.IsNaN(value) && !math.IsInf(value, 0) && math.Trunc(value) == value
	case string:
		hasSequence = len(value) > 0 && len(value) <= 64
	default:
		hasSequence = false
	}
	if hasSequence && a.ConversationID != "" && !a.Timestamp.IsZero() {
		a.dedupeKey = fmt.Sprintf("%s\x00%s\x00%v\x00%s\x00%s", a.ConversationID, a.Timestamp.UTC().Format(time.RFC3339Nano), sequence, name, a.Trigger)
		a.Coverage = "native_activation"
	}
	return a, true
}

func (s *Store) retainSkillActivation(record LogRecord) {
	a, ok := providerSkillActivation(record)
	if !ok {
		return
	}
	if a.dedupeKey != "" {
		if _, exists := s.providerSkillKeys[a.dedupeKey]; exists {
			return
		}
		s.providerSkillKeys[a.dedupeKey] = struct{}{}
	}
	for _, evicted := range s.providerSkillActivations.pushWithEvicted([]ProviderSkillActivation{a}) {
		delete(s.providerSkillKeys, evicted.dedupeKey)
	}
}

func (s *Store) retainSkillInjection(point MetricDataPoint) {
	if point.Name != "codex.skill.injected" || !strings.EqualFold(point.Type, "sum") || !point.IsMonotonic || point.Value < 0 || math.IsNaN(point.Value) || math.IsInf(point.Value, 0) || point.Flags&1 != 0 {
		return
	}
	name := providerTelemetryAttributeString(point.Attributes, "skill")
	if name == "" {
		return
	}
	s.providerSkillInjections.push([]ProviderSkillInjection{{
		Provider: "codex", SkillName: name,
		Status: providerTelemetryAttributeString(point.Attributes, "status"),
		Value:  point.Value, Temporality: point.Temporality, Timestamp: point.Timestamp,
		ServiceName: point.Resource.ServiceName,
	}})
}

func (s *Store) SnapshotProviderSkillActivations() []ProviderSkillActivation {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.providerSkillActivations.snapshot()
}

func (s *Store) SnapshotProviderSkillInjections() []ProviderSkillInjection {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.providerSkillInjections.snapshot()
}
