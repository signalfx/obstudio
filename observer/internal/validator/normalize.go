package validator

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

type normalizedLine struct {
	Entity *Entity
	Stats  *weaverStats
}

func normalizeLine(raw []byte, now time.Time) (normalizedLine, bool, error) {
	line := bytes.TrimSpace(raw)
	if len(line) == 0 || line[0] != '{' {
		return normalizedLine{}, false, nil
	}

	var payload map[string]any
	if err := json.Unmarshal(line, &payload); err != nil {
		return normalizedLine{}, false, err
	}
	if len(payload) == 0 {
		return normalizedLine{}, false, nil
	}

	if stats, ok := decodeStats(payload); ok {
		return normalizedLine{Stats: &stats}, true, nil
	}

	entityType, entityPayload, ok := topLevelEntity(payload)
	if !ok {
		return normalizedLine{}, false, nil
	}

	signal := signalRefFromEntity(entityType, entityPayload)
	entity := Entity{
		Key:       entityKey(signal),
		Signal:    signal,
		UpdatedAt: now,
	}
	collectAdvice(entityPayload, signal, now, &entity)
	if len(entity.Findings) == 0 {
		return normalizedLine{}, false, nil
	}
	for _, finding := range entity.Findings {
		entity.HighestSeverity = maxSeverity(entity.HighestSeverity, finding.Severity)
	}
	return normalizedLine{Entity: &entity}, true, nil
}

func decodeStats(payload map[string]any) (weaverStats, bool) {
	if _, ok := payload["total_entities"]; !ok {
		if _, ok = payload["advice_level_counts"]; !ok {
			return weaverStats{}, false
		}
	}

	out := weaverStats{
		AdviceLevelCounts:        map[string]int{},
		HighestAdviceLevelCounts: map[string]int{},
		TotalEntitiesByType:      map[string]int{},
	}
	out.TotalEntities = intValue(payload["total_entities"])
	out.TotalAdvisories = intValue(payload["total_advisories"])
	out.NoAdviceCount = intValue(payload["no_advice_count"])
	copyIntMap(out.AdviceLevelCounts, payload["advice_level_counts"])
	copyIntMap(out.HighestAdviceLevelCounts, payload["highest_advice_level_counts"])
	copyIntMap(out.TotalEntitiesByType, payload["total_entities_by_type"])
	return out, true
}

func topLevelEntity(payload map[string]any) (string, map[string]any, bool) {
	for _, key := range []string{"span", "metric", "log", "resource"} {
		value, ok := payload[key]
		if !ok {
			continue
		}
		entity, ok := value.(map[string]any)
		if !ok {
			continue
		}
		return key, entity, true
	}
	return "", nil, false
}

func signalRefFromEntity(entityType string, entity map[string]any) SignalRef {
	ref := SignalRef{
		Type:        entityType,
		ServiceName: serviceNameFromEntity(entity),
		TraceID:     stringValue(entity["trace_id"]),
		SpanID:      stringValue(firstNonNil(entity["span_id"], entity["id"])),
		SpanName:    stringValue(entity["name"]),
		MetricName:  stringValue(entity["name"]),
		ScopeName:   scopeNameFromEntity(entity),
		LogBody:     bodyValue(entity["body"]),
	}

	if ref.TraceID == "" {
		ref.TraceID = stringValue(entity["traceId"])
	}
	if ref.SpanID == "" {
		ref.SpanID = stringValue(entity["spanId"])
	}
	if ref.ServiceName == "" {
		ref.ServiceName = serviceNameFromAttrs(entity["resource_attributes"])
	}
	switch entityType {
	case "metric":
		ref.SpanName = ""
		ref.LogBody = ""
	case "log":
		ref.MetricName = ""
		ref.SpanName = ""
	case "resource":
		ref.TraceID = ""
		ref.SpanID = ""
		ref.SpanName = ""
		ref.MetricName = ""
		ref.LogBody = ""
	}
	return ref
}

func collectAdvice(value any, signal SignalRef, now time.Time, entity *Entity) {
	switch v := value.(type) {
	case map[string]any:
		if result, ok := v["live_check_result"].(map[string]any); ok {
			if allAdvice, ok := result["all_advice"].([]any); ok {
				for _, rawAdvice := range allAdvice {
					advice, ok := rawAdvice.(map[string]any)
					if !ok {
						continue
					}
					finding := Finding{
						EntityKey: entity.Key,
						Source:    "weaver",
						RuleID:    stringValue(advice["id"]),
						Severity:  Severity(strings.ToLower(stringValue(advice["level"]))),
						Message:   stringValue(advice["message"]),
						Context:   mapValue(advice["context"]),
						Signal:    mergeSignal(signal, advice),
						UpdatedAt: now,
					}
					if finding.RuleID == "" || finding.Severity == "" || finding.Message == "" {
						continue
					}
					entity.Findings = append(entity.Findings, finding)
				}
			}
		}
		for key, child := range v {
			if key == "live_check_result" {
				continue
			}
			collectAdvice(child, signal, now, entity)
		}
	case []any:
		for _, child := range v {
			collectAdvice(child, signal, now, entity)
		}
	}
}

func mergeSignal(base SignalRef, advice map[string]any) SignalRef {
	out := base
	if signalType := stringValue(advice["signal_type"]); signalType != "" {
		out.Type = signalType
	}
	if signalName := stringValue(advice["signal_name"]); signalName != "" {
		switch out.Type {
		case "metric":
			out.MetricName = signalName
		case "span", "span_event":
			out.SpanName = signalName
		case "log":
			if out.LogBody == "" {
				out.LogBody = signalName
			}
		}
	}
	return out
}

func entityKey(signal SignalRef) string {
	switch signal.Type {
	case "span", "span_event":
		if signal.TraceID != "" || signal.SpanID != "" {
			return fmt.Sprintf("span:%s:%s", signal.TraceID, signal.SpanID)
		}
		return fmt.Sprintf("span:%s:%s", signal.ServiceName, signal.SpanName)
	case "metric":
		return fmt.Sprintf("metric:%s:%s:%s", signal.ServiceName, signal.ScopeName, signal.MetricName)
	case "log":
		return fmt.Sprintf("log:%s:%s:%s:%s", signal.ServiceName, signal.TraceID, signal.SpanID, signal.LogBody)
	case "resource":
		return fmt.Sprintf("resource:%s", signal.ServiceName)
	default:
		return fmt.Sprintf("%s:%s:%s", signal.Type, signal.ServiceName, signal.SpanName)
	}
}

func serviceNameFromEntity(entity map[string]any) string {
	if resource, ok := entity["resource"].(map[string]any); ok {
		if serviceName := stringValue(resource["service_name"]); serviceName != "" {
			return serviceName
		}
		if serviceName := serviceNameFromAttrs(resource["attributes"]); serviceName != "" {
			return serviceName
		}
	}
	return serviceNameFromAttrs(entity["resource_attributes"])
}

func scopeNameFromEntity(entity map[string]any) string {
	if scope, ok := entity["scope"].(map[string]any); ok {
		if name := stringValue(scope["name"]); name != "" {
			return name
		}
	}
	return stringValue(entity["scope_name"])
}

func serviceNameFromAttrs(raw any) string {
	attrs := flattenAttrs(raw)
	if serviceName := stringValue(attrs["service.name"]); serviceName != "" {
		return serviceName
	}
	return stringValue(attrs["service_name"])
}

func flattenAttrs(raw any) map[string]any {
	switch attrs := raw.(type) {
	case map[string]any:
		if nested, ok := attrs["attributes"]; ok {
			return flattenAttrs(nested)
		}
		out := make(map[string]any, len(attrs))
		for key, value := range attrs {
			out[key] = attributeValue(value)
		}
		return out
	case []any:
		out := make(map[string]any, len(attrs))
		for _, item := range attrs {
			entry, ok := item.(map[string]any)
			if !ok {
				continue
			}
			key := stringValue(firstNonNil(entry["name"], entry["key"]))
			if key == "" {
				continue
			}
			out[key] = attributeValue(entry["value"])
		}
		return out
	default:
		return map[string]any{}
	}
}

func attributeValue(raw any) any {
	switch value := raw.(type) {
	case map[string]any:
		for _, key := range []string{"stringValue", "string_value", "intValue", "int_value", "doubleValue", "double_value", "boolValue", "bool_value"} {
			if candidate, ok := value[key]; ok {
				return candidate
			}
		}
		if len(value) == 1 {
			for _, candidate := range value {
				return candidate
			}
		}
		return value
	default:
		return value
	}
}

func bodyValue(raw any) string {
	switch body := raw.(type) {
	case string:
		return body
	case map[string]any:
		return stringValue(attributeValue(body))
	default:
		return stringValue(body)
	}
}

func copyIntMap(dst map[string]int, raw any) {
	src, ok := raw.(map[string]any)
	if !ok {
		return
	}
	for key, value := range src {
		dst[key] = intValue(value)
	}
}

func mapValue(raw any) map[string]any {
	value, ok := raw.(map[string]any)
	if !ok {
		return nil
	}
	out := make(map[string]any, len(value))
	for key, item := range value {
		out[key] = attributeValue(item)
	}
	return out
}

func stringValue(raw any) string {
	switch value := raw.(type) {
	case string:
		return value
	case fmt.Stringer:
		return value.String()
	case float64:
		return fmt.Sprintf("%.0f", value)
	case int:
		return fmt.Sprintf("%d", value)
	case int64:
		return fmt.Sprintf("%d", value)
	case bool:
		if value {
			return "true"
		}
		return "false"
	default:
		return ""
	}
}

func intValue(raw any) int {
	switch value := raw.(type) {
	case float64:
		return int(value)
	case int:
		return value
	case int64:
		return int(value)
	case json.Number:
		n, _ := value.Int64()
		return int(n)
	default:
		return 0
	}
}

func firstNonNil(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}
