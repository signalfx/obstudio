package store

import (
	"encoding/json"
	"fmt"
	"time"
)

// AddSkillWorkflowSpans retains recorder observations independently of a short-lived
// HTTP connection. Replaying an unchanged journal is idempotent while retained.
func (s *Store) AddSkillWorkflowSpans(spans []Span) ([]Span, error) {
	s.mu.Lock()
	existing := map[string]Span{}
	for _, span := range s.spans.snapshot() {
		if span.Scope.Name == "obstudio.skill-workflows" {
			existing[span.TraceID+span.SpanID] = span
		}
	}
	var fresh []Span
	for _, span := range spans {
		if span.Attributes["skill.observation"] == "telemetry_evaluation" {
			parent, retained := existing[span.TraceID+span.ParentSpanID]
			if !retained || parent.Attributes["skill.observation"] != "explicit_workflow_interval" {
				s.mu.Unlock()
				return nil, fmt.Errorf("source workflow is no longer retained; replay its journal before evaluating")
			}
		}
		if prior, ok := existing[span.TraceID+span.SpanID]; ok {
			a, _ := json.Marshal(prior)
			b, _ := json.Marshal(span)
			if string(a) != string(b) {
				s.mu.Unlock()
				return nil, fmt.Errorf("conflicting retained workflow event")
			}
			continue
		}
		fresh = append(fresh, span)
		existing[span.TraceID+span.SpanID] = span
	}
	if len(fresh) == 0 {
		s.mu.Unlock()
		return fresh, nil
	}
	// Recorder activity is not an application restart, even after an idle gap.
	for i := range fresh {
		s.spanIngestRevision++
		fresh[i].ingestRevision = s.spanIngestRevision
		fresh[i].agentReceipt = false
		fresh[i].ownerConnID = "skill-workflows"
		s.pushSpanWithAgentIndex(fresh[i])
	}
	s.captureProviderTraceSpans(fresh)
	s.captureCompletedProviderTasks(fresh)
	changedAt := time.Now()
	s.lastIngest = changedAt
	s.mu.Unlock()
	s.runChangeCallback(changedAt)
	s.notify(SignalTraces)
	return fresh, nil
}
