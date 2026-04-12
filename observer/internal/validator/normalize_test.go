package validator

import (
	"testing"
	"time"
)

func TestNormalizeLineEntity(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	line := []byte(`{
		"span": {
			"name": "GET /orders",
			"trace_id": "trace-1",
			"span_id": "span-1",
			"resource": {
				"attributes": [
					{"name": "service.name", "value": "checkout"}
				]
			},
			"live_check_result": {
				"all_advice": [
					{
						"id": "deprecated",
						"level": "improvement",
						"message": "Uses deprecated attribute",
						"context": {"attribute_name": "http.method"},
						"signal_type": "span",
						"signal_name": "GET /orders"
					}
				]
			}
		}
	}`)

	normalized, ok, err := normalizeLine(line, now)
	if err != nil {
		t.Fatalf("normalizeLine returned error: %v", err)
	}
	if !ok {
		t.Fatalf("expected line to normalize")
	}
	if normalized.Entity == nil {
		t.Fatalf("expected entity output")
	}

	entity := normalized.Entity
	if entity.Key != "span:trace-1:span-1" {
		t.Fatalf("unexpected entity key: %s", entity.Key)
	}
	if entity.Signal.ServiceName != "checkout" {
		t.Fatalf("unexpected service name: %s", entity.Signal.ServiceName)
	}
	if entity.HighestSeverity != SeverityImprovement {
		t.Fatalf("unexpected highest severity: %s", entity.HighestSeverity)
	}
	if len(entity.Findings) != 1 {
		t.Fatalf("expected 1 finding, got %d", len(entity.Findings))
	}
	if entity.Findings[0].RuleID != "deprecated" {
		t.Fatalf("unexpected rule id: %s", entity.Findings[0].RuleID)
	}
}

func TestNormalizeLineStats(t *testing.T) {
	line := []byte(`{
		"advice_level_counts": {"violation": 2, "improvement": 1},
		"highest_advice_level_counts": {"violation": 2},
		"total_advisories": 3,
		"total_entities": 4,
		"no_advice_count": 1,
		"total_entities_by_type": {"span": 2, "metric": 2}
	}`)

	normalized, ok, err := normalizeLine(line, time.Now())
	if err != nil {
		t.Fatalf("normalizeLine returned error: %v", err)
	}
	if !ok {
		t.Fatalf("expected line to normalize")
	}
	if normalized.Stats == nil {
		t.Fatalf("expected stats output")
	}
	if normalized.Stats.TotalEntities != 4 {
		t.Fatalf("unexpected total entities: %d", normalized.Stats.TotalEntities)
	}
	if normalized.Stats.AdviceLevelCounts["violation"] != 2 {
		t.Fatalf("unexpected violation count: %d", normalized.Stats.AdviceLevelCounts["violation"])
	}
}

func TestNormalizeLineIgnoresBanner(t *testing.T) {
	normalized, ok, err := normalizeLine([]byte("Starting live-check"), time.Now())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ok || normalized.Entity != nil || normalized.Stats != nil {
		t.Fatalf("expected non-JSON line to be ignored")
	}
}
