package store

import (
	"encoding/json"
	"fmt"
)

// AddSkillWorkflowSpans retains recorder observations independently of a short-lived
// HTTP connection. Replaying an unchanged journal is idempotent while retained.
func (s *Store) AddSkillWorkflowSpans(spans []Span) ([]Span, error) {
	s.skillWorkflowMu.Lock()
	defer s.skillWorkflowMu.Unlock()
	existing := map[string]Span{}
	for _, span := range s.SnapshotSpans() {
		if span.Scope.Name == "obstudio.skill-workflows" {
			existing[span.TraceID+span.SpanID] = span
		}
	}
	var fresh []Span
	for _, span := range spans {
		if prior, ok := existing[span.TraceID+span.SpanID]; ok {
			a, _ := json.Marshal(prior)
			b, _ := json.Marshal(span)
			if string(a) != string(b) {
				return nil, fmt.Errorf("conflicting retained workflow event")
			}
			continue
		}
		fresh = append(fresh, span)
	}
	if len(fresh) > 0 {
		s.AddSpansForConnection("skill-workflows", fresh)
	}
	return fresh, nil
}
