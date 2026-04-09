package otlp

import (
	"encoding/hex"

	"github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

func ConvertTraces(td ptrace.Traces) []store.Span {
	var out []store.Span
	rss := td.ResourceSpans()
	for i := 0; i < rss.Len(); i++ {
		rs := rss.At(i)
		res := convertResource(rs.Resource(), rs.SchemaUrl())
		sss := rs.ScopeSpans()
		for j := 0; j < sss.Len(); j++ {
			ss := sss.At(j)
			scope := convertScope(ss.Scope(), ss.SchemaUrl())
			spans := ss.Spans()
			for k := 0; k < spans.Len(); k++ {
				sp := spans.At(k)
				start := sp.StartTimestamp().AsTime()
				end := sp.EndTimestamp().AsTime()
				out = append(out, store.Span{
					TraceID:      traceIDStr(sp.TraceID()),
					SpanID:       spanIDStr(sp.SpanID()),
					ParentSpanID: spanIDStr(sp.ParentSpanID()),
					Name:         sp.Name(),
					Kind:         spanKindString(sp.Kind()),
					StartTime:    start,
					EndTime:      end,
					DurationMs:   float64(end.Sub(start).Microseconds()) / 1000.0,
					Status:       convertSpanStatus(sp.Status()),
					Attributes:   mapToGoMap(sp.Attributes()),
					Events:       convertEvents(sp.Events()),
					Links:        convertLinks(sp.Links()),
					Resource:     res,
					Scope:        scope,
				})
			}
		}
	}
	return out
}

func ConvertMetrics(md pmetric.Metrics) []store.MetricDataPoint {
	var out []store.MetricDataPoint
	rms := md.ResourceMetrics()
	for i := 0; i < rms.Len(); i++ {
		rm := rms.At(i)
		res := convertResource(rm.Resource(), rm.SchemaUrl())
		sms := rm.ScopeMetrics()
		for j := 0; j < sms.Len(); j++ {
			sm := sms.At(j)
			scope := convertScope(sm.Scope(), sm.SchemaUrl())
			ms := sm.Metrics()
			for k := 0; k < ms.Len(); k++ {
				out = append(out, convertMetric(ms.At(k), res, scope)...)
			}
		}
	}
	return out
}

func ConvertLogs(ld plog.Logs) []store.LogRecord {
	var out []store.LogRecord
	rls := ld.ResourceLogs()
	for i := 0; i < rls.Len(); i++ {
		rl := rls.At(i)
		res := convertResource(rl.Resource(), rl.SchemaUrl())
		sls := rl.ScopeLogs()
		for j := 0; j < sls.Len(); j++ {
			sl := sls.At(j)
			scope := convertScope(sl.Scope(), sl.SchemaUrl())
			lrs := sl.LogRecords()
			for k := 0; k < lrs.Len(); k++ {
				lr := lrs.At(k)
				out = append(out, store.LogRecord{
					Timestamp:      lr.Timestamp().AsTime(),
					SeverityNumber: int32(lr.SeverityNumber()),
					SeverityText:   lr.SeverityText(),
					Body:           valueString(lr.Body()),
					Attributes:     mapToGoMap(lr.Attributes()),
					TraceID:        traceIDStr(lr.TraceID()),
					SpanID:         spanIDStr(lr.SpanID()),
					Resource:       res,
					Scope:          scope,
				})
			}
		}
	}
	return out
}

func convertMetric(m pmetric.Metric, res store.Resource, scope store.Scope) []store.MetricDataPoint {
	name := m.Name()
	desc := m.Description()
	unit := m.Unit()

	switch m.Type() {
	case pmetric.MetricTypeGauge:
		return convertNumberDataPoints(m.Gauge().DataPoints(), name, desc, unit, "gauge", "", false, res, scope)
	case pmetric.MetricTypeSum:
		s := m.Sum()
		return convertNumberDataPoints(s.DataPoints(), name, desc, unit, "sum", temporalityString(s.AggregationTemporality()), s.IsMonotonic(), res, scope)
	case pmetric.MetricTypeHistogram:
		h := m.Histogram()
		return convertHistogramDataPoints(h.DataPoints(), name, desc, unit, temporalityString(h.AggregationTemporality()), res, scope)
	case pmetric.MetricTypeSummary:
		return convertSummaryDataPoints(m.Summary().DataPoints(), name, desc, unit, res, scope)
	case pmetric.MetricTypeExponentialHistogram:
		eh := m.ExponentialHistogram()
		return convertExpHistogramDataPoints(eh.DataPoints(), name, desc, unit, temporalityString(eh.AggregationTemporality()), res, scope)
	}
	return nil
}

func convertNumberDataPoints(dps pmetric.NumberDataPointSlice, name, desc, unit, typ, temp string, monotonic bool, res store.Resource, scope store.Scope) []store.MetricDataPoint {
	out := make([]store.MetricDataPoint, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		mdp := store.MetricDataPoint{
			Name: name, Description: desc, Unit: unit, Type: typ,
			Timestamp: dp.Timestamp().AsTime(), StartTime: dp.StartTimestamp().AsTime(),
			Attributes: mapToGoMap(dp.Attributes()), Flags: int(dp.Flags()),
			Resource: res, Scope: scope, IsMonotonic: monotonic, Temporality: temp,
		}
		switch dp.ValueType() {
		case pmetric.NumberDataPointValueTypeDouble:
			mdp.Value = dp.DoubleValue()
		case pmetric.NumberDataPointValueTypeInt:
			mdp.Value = float64(dp.IntValue())
		}
		out = append(out, mdp)
	}
	return out
}

func convertHistogramDataPoints(dps pmetric.HistogramDataPointSlice, name, desc, unit, temp string, res store.Resource, scope store.Scope) []store.MetricDataPoint {
	out := make([]store.MetricDataPoint, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		out = append(out, store.MetricDataPoint{
			Name: name, Description: desc, Unit: unit, Type: "histogram",
			Timestamp: dp.Timestamp().AsTime(), StartTime: dp.StartTimestamp().AsTime(),
			Attributes: mapToGoMap(dp.Attributes()), Flags: int(dp.Flags()),
			Resource: res, Scope: scope, Temporality: temp,
			Count: dp.Count(), Sum: dp.Sum(), Min: dp.Min(), Max: dp.Max(),
			BucketCounts:   dp.BucketCounts().AsRaw(),
			ExplicitBounds: dp.ExplicitBounds().AsRaw(),
		})
	}
	return out
}

func convertSummaryDataPoints(dps pmetric.SummaryDataPointSlice, name, desc, unit string, res store.Resource, scope store.Scope) []store.MetricDataPoint {
	out := make([]store.MetricDataPoint, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		qvs := dp.QuantileValues()
		quantiles := make([]store.QuantileValue, 0, qvs.Len())
		for j := 0; j < qvs.Len(); j++ {
			qv := qvs.At(j)
			quantiles = append(quantiles, store.QuantileValue{Quantile: qv.Quantile(), Value: qv.Value()})
		}
		out = append(out, store.MetricDataPoint{
			Name: name, Description: desc, Unit: unit, Type: "summary",
			Timestamp: dp.Timestamp().AsTime(), StartTime: dp.StartTimestamp().AsTime(),
			Attributes: mapToGoMap(dp.Attributes()), Flags: int(dp.Flags()),
			Resource: res, Scope: scope, Count: dp.Count(), Sum: dp.Sum(), Quantiles: quantiles,
		})
	}
	return out
}

func convertExpHistogramDataPoints(dps pmetric.ExponentialHistogramDataPointSlice, name, desc, unit, temp string, res store.Resource, scope store.Scope) []store.MetricDataPoint {
	out := make([]store.MetricDataPoint, 0, dps.Len())
	for i := 0; i < dps.Len(); i++ {
		dp := dps.At(i)
		out = append(out, store.MetricDataPoint{
			Name: name, Description: desc, Unit: unit, Type: "exponential_histogram",
			Timestamp: dp.Timestamp().AsTime(), StartTime: dp.StartTimestamp().AsTime(),
			Attributes: mapToGoMap(dp.Attributes()), Flags: int(dp.Flags()),
			Resource: res, Scope: scope, Temporality: temp,
			Count: dp.Count(), Sum: dp.Sum(), Min: dp.Min(), Max: dp.Max(),
		})
	}
	return out
}

func convertResource(r pcommon.Resource, schemaURL string) store.Resource {
	attrs := mapToGoMap(r.Attributes())
	svcName, _ := attrs["service.name"].(string)
	return store.Resource{ServiceName: svcName, Attributes: attrs, SchemaURL: schemaURL}
}

func convertScope(s pcommon.InstrumentationScope, schemaURL string) store.Scope {
	return store.Scope{Name: s.Name(), Version: s.Version(), SchemaURL: schemaURL}
}

func convertSpanStatus(s ptrace.Status) store.SpanStatus {
	return store.SpanStatus{Code: statusCodeString(s.Code()), Message: s.Message()}
}

func convertEvents(evts ptrace.SpanEventSlice) []store.SpanEvent {
	out := make([]store.SpanEvent, 0, evts.Len())
	for i := 0; i < evts.Len(); i++ {
		e := evts.At(i)
		out = append(out, store.SpanEvent{
			Name:       e.Name(),
			Timestamp:  e.Timestamp().AsTime(),
			Attributes: mapToGoMap(e.Attributes()),
		})
	}
	return out
}

func convertLinks(links ptrace.SpanLinkSlice) []store.SpanLink {
	out := make([]store.SpanLink, 0, links.Len())
	for i := 0; i < links.Len(); i++ {
		l := links.At(i)
		out = append(out, store.SpanLink{
			TraceID:    traceIDStr(l.TraceID()),
			SpanID:     spanIDStr(l.SpanID()),
			Attributes: mapToGoMap(l.Attributes()),
		})
	}
	return out
}

func mapToGoMap(m pcommon.Map) map[string]any {
	if m.Len() == 0 {
		return map[string]any{}
	}
	out := make(map[string]any, m.Len())
	m.Range(func(k string, v pcommon.Value) bool {
		out[k] = valueToGo(v)
		return true
	})
	return out
}

func valueToGo(v pcommon.Value) any {
	switch v.Type() {
	case pcommon.ValueTypeStr:
		return v.Str()
	case pcommon.ValueTypeBool:
		return v.Bool()
	case pcommon.ValueTypeInt:
		return v.Int()
	case pcommon.ValueTypeDouble:
		return v.Double()
	case pcommon.ValueTypeBytes:
		return hex.EncodeToString(v.Bytes().AsRaw())
	case pcommon.ValueTypeSlice:
		sl := v.Slice()
		arr := make([]any, 0, sl.Len())
		for i := 0; i < sl.Len(); i++ {
			arr = append(arr, valueToGo(sl.At(i)))
		}
		return arr
	case pcommon.ValueTypeMap:
		return mapToGoMap(v.Map())
	}
	return nil
}

func valueString(v pcommon.Value) string {
	if v.Type() == pcommon.ValueTypeStr {
		return v.Str()
	}
	return v.AsString()
}

func traceIDStr(id pcommon.TraceID) string {
	b := id
	if b.IsEmpty() {
		return ""
	}
	return hex.EncodeToString(b[:])
}

func spanIDStr(id pcommon.SpanID) string {
	b := id
	if b.IsEmpty() {
		return ""
	}
	return hex.EncodeToString(b[:])
}

func spanKindString(k ptrace.SpanKind) string {
	switch k {
	case ptrace.SpanKindInternal:
		return "INTERNAL"
	case ptrace.SpanKindServer:
		return "SERVER"
	case ptrace.SpanKindClient:
		return "CLIENT"
	case ptrace.SpanKindProducer:
		return "PRODUCER"
	case ptrace.SpanKindConsumer:
		return "CONSUMER"
	default:
		return "UNSPECIFIED"
	}
}

func statusCodeString(c ptrace.StatusCode) string {
	switch c {
	case ptrace.StatusCodeOk:
		return "OK"
	case ptrace.StatusCodeError:
		return "ERROR"
	default:
		return "UNSET"
	}
}

func temporalityString(t pmetric.AggregationTemporality) string {
	switch t {
	case pmetric.AggregationTemporalityDelta:
		return "delta"
	case pmetric.AggregationTemporalityCumulative:
		return "cumulative"
	default:
		return ""
	}
}
