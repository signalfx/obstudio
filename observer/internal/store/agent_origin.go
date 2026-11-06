package store

import "strings"

// AgentOriginRecord is any record the OTLP receiver stores.
type AgentOriginRecord interface {
	Span | MetricDataPoint | LogRecord
}

// IsAgentOrigin reports whether a received record is agent-native telemetry
// (Claude Code, Codex, or obstudio's own agent-lifecycle hook) rather than
// data from the user's application. It is the one owner of that rule for
// callers outside token accounting; the provider classifiers are unchanged.
//
// A record is agent-native when any of these hold:
//  1. a provider classifier recognizes it (ClassifyProviderUsageLog,
//     ClassifyProviderUsageMetric, or the provider agent-span rule);
//  2. its resource service.name, trimmed and case-folded, is claude-code or
//     starts with it, is codex, or starts with codex- or codex_;
//  3. its metric name, log event.name or body, or span name starts with
//     claude_code. or codex.;
//  4. it is a log whose event.name or body is obstudio.repository_correlation,
//     matched by name only so a malformed hook event is excluded too.
//
// Matching on service.name is best-effort: a user app named claude-code-* or
// codex-* is treated as agent-native too.
func IsAgentOrigin[T AgentOriginRecord](record T) bool {
	switch r := any(record).(type) {
	case Span:
		return isProviderAgentSpan(r) || agentServiceName(r.Resource.ServiceName) || agentName(r.Name)
	case MetricDataPoint:
		return ClassifyProviderUsageMetric(r) != ProviderUsageMetricUnknown ||
			agentServiceName(r.Resource.ServiceName) || agentName(r.Name)
	case LogRecord:
		if ClassifyProviderUsageLog(r) != ProviderUsageLogUnknown || agentServiceName(r.Resource.ServiceName) {
			return true
		}
		eventName := normalizedProviderTelemetryString(r.Attributes["event.name"])
		body := strings.ToLower(strings.TrimSpace(r.Body))
		if eventName == "obstudio.repository_correlation" || body == "obstudio.repository_correlation" {
			return true
		}
		return agentName(eventName) || agentName(body)
	}
	return false
}

func agentServiceName(name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	return strings.HasPrefix(n, "claude-code") || n == "codex" ||
		strings.HasPrefix(n, "codex-") || strings.HasPrefix(n, "codex_")
}

func agentName(name string) bool {
	n := strings.ToLower(strings.TrimSpace(name))
	return strings.HasPrefix(n, "claude_code.") || strings.HasPrefix(n, "codex.")
}

// Receipt is one accepted OTLP payload on the application ingest path, after
// it is stored. Exactly one of its slices is non-empty.
type Receipt struct {
	Spans   []Span
	Metrics []MetricDataPoint
	Logs    []LogRecord
}

// SetReceiptCallback installs fn, called after each accepted application OTLP
// payload (traces, metrics or logs) is stored. It is not called for the agent
// span route or for internal logs. fn runs on the receiving goroutine, so it
// must return quickly.
func (s *Store) SetReceiptCallback(fn func(Receipt)) {
	s.receiptMu.Lock()
	s.receipt = fn
	s.receiptMu.Unlock()
}

func (s *Store) runReceiptCallback(r Receipt) {
	s.receiptMu.RLock()
	fn := s.receipt
	s.receiptMu.RUnlock()
	if fn != nil && len(r.Spans)+len(r.Metrics)+len(r.Logs) > 0 {
		fn(r)
	}
}
