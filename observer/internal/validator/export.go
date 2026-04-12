package validator

import (
	"encoding/hex"
	"encoding/json"
	"fmt"

	telemetrystore "github.com/signalfx/obstudio/observer/internal/store"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

type snapshotSignals struct {
	traces  ptrace.Traces
	metrics pmetric.Metrics
	logs    plog.Logs
}

func buildSnapshotSignals(snapshot telemetrystore.TelemetrySnapshot) (snapshotSignals, error) {
	traces, err := buildSnapshotTraces(snapshot.Spans)
	if err != nil {
		return snapshotSignals{}, err
	}
	metrics, err := buildSnapshotMetrics(snapshot.Metrics)
	if err != nil {
		return snapshotSignals{}, err
	}
	logs, err := buildSnapshotLogs(snapshot.Logs)
	if err != nil {
		return snapshotSignals{}, err
	}
	return snapshotSignals{traces: traces, metrics: metrics, logs: logs}, nil
}

func buildSnapshotTraces(spans []telemetrystore.Span) (ptrace.Traces, error) {
	td := ptrace.NewTraces()
	resourceMap := make(map[string]ptrace.ResourceSpans)

	for _, span := range spans {
		rs, err := getOrAppendResourceSpans(td.ResourceSpans(), resourceMap, span.Resource)
		if err != nil {
			return ptrace.NewTraces(), err
		}
		scopeSpans := getOrAppendScopeSpans(rs.ScopeSpans(), scopeKey(span.Scope))
		pspan := scopeSpans.Spans().AppendEmpty()

		traceID, err := decodeTraceID(span.TraceID)
		if err != nil {
			return ptrace.NewTraces(), fmt.Errorf("decode trace id: %w", err)
		}
		spanID, err := decodeSpanID(span.SpanID)
		if err != nil {
			return ptrace.NewTraces(), fmt.Errorf("decode span id: %w", err)
		}
		parentSpanID, err := decodeOptionalSpanID(span.ParentSpanID)
		if err != nil {
			return ptrace.NewTraces(), fmt.Errorf("decode parent span id: %w", err)
		}

		pspan.SetTraceID(traceID)
		pspan.SetSpanID(spanID)
		if parentSpanID != ([8]byte{}) {
			pspan.SetParentSpanID(parentSpanID)
		}
		pspan.SetName(span.Name)
		pspan.SetKind(spanKindFromString(span.Kind))
		pspan.SetStartTimestamp(pcommon.NewTimestampFromTime(span.StartTime))
		pspan.SetEndTimestamp(pcommon.NewTimestampFromTime(span.EndTime))
		if err := setMapValues(pspan.Attributes(), span.Attributes); err != nil {
			return ptrace.NewTraces(), err
		}
		status := pspan.Status()
		status.SetCode(statusCodeFromString(span.Status.Code))
		status.SetMessage(span.Status.Message)

		events := pspan.Events()
		for _, event := range span.Events {
			pEvent := events.AppendEmpty()
			pEvent.SetName(event.Name)
			pEvent.SetTimestamp(pcommon.NewTimestampFromTime(event.Timestamp))
			if err := setMapValues(pEvent.Attributes(), event.Attributes); err != nil {
				return ptrace.NewTraces(), err
			}
		}

		links := pspan.Links()
		for _, link := range span.Links {
			pLink := links.AppendEmpty()
			linkTraceID, err := decodeTraceID(link.TraceID)
			if err != nil {
				return ptrace.NewTraces(), fmt.Errorf("decode link trace id: %w", err)
			}
			linkSpanID, err := decodeSpanID(link.SpanID)
			if err != nil {
				return ptrace.NewTraces(), fmt.Errorf("decode link span id: %w", err)
			}
			pLink.SetTraceID(linkTraceID)
			pLink.SetSpanID(linkSpanID)
			if err := setMapValues(pLink.Attributes(), link.Attributes); err != nil {
				return ptrace.NewTraces(), err
			}
		}
	}

	return td, nil
}

func buildSnapshotMetrics(points []telemetrystore.MetricDataPoint) (pmetric.Metrics, error) {
	md := pmetric.NewMetrics()
	resourceMap := make(map[string]pmetric.ResourceMetrics)
	metricMap := make(map[string]pmetric.Metric)

	for _, point := range points {
		rm, err := getOrAppendResourceMetrics(md.ResourceMetrics(), resourceMap, point.Resource)
		if err != nil {
			return pmetric.NewMetrics(), err
		}
		sm := getOrAppendScopeMetrics(rm.ScopeMetrics(), scopeKey(point.Scope))

		key := metricKey(point)
		metric, ok := metricMap[key]
		if !ok {
			metric = sm.Metrics().AppendEmpty()
			metric.SetName(point.Name)
			metric.SetDescription(point.Description)
			metric.SetUnit(point.Unit)
			initializeMetric(metric, point)
			metricMap[key] = metric
		}

		switch point.Type {
		case "gauge":
			dp := metric.Gauge().DataPoints().AppendEmpty()
			populateNumberDataPoint(dp, point)
		case "sum", "counter":
			dp := metric.Sum().DataPoints().AppendEmpty()
			populateNumberDataPoint(dp, point)
		case "histogram":
			dp := metric.Histogram().DataPoints().AppendEmpty()
			populateHistogramDataPoint(dp, point)
		case "summary":
			dp := metric.Summary().DataPoints().AppendEmpty()
			populateSummaryDataPoint(dp, point)
		case "exponential_histogram":
			dp := metric.ExponentialHistogram().DataPoints().AppendEmpty()
			populateExpHistogramDataPoint(dp, point)
		default:
			dp := metric.Gauge().DataPoints().AppendEmpty()
			populateNumberDataPoint(dp, point)
		}
	}

	return md, nil
}

func buildSnapshotLogs(records []telemetrystore.LogRecord) (plog.Logs, error) {
	ld := plog.NewLogs()
	resourceMap := make(map[string]plog.ResourceLogs)

	for _, record := range records {
		rl, err := getOrAppendResourceLogs(ld.ResourceLogs(), resourceMap, record.Resource)
		if err != nil {
			return plog.NewLogs(), err
		}
		scopeLogs := getOrAppendScopeLogs(rl.ScopeLogs(), scopeKey(record.Scope))
		logRecord := scopeLogs.LogRecords().AppendEmpty()

		logRecord.SetTimestamp(pcommon.NewTimestampFromTime(record.Timestamp))
		logRecord.SetSeverityNumber(plog.SeverityNumber(record.SeverityNumber))
		logRecord.SetSeverityText(record.SeverityText)
		logRecord.Body().SetStr(record.Body)
		if err := setMapValues(logRecord.Attributes(), record.Attributes); err != nil {
			return plog.NewLogs(), err
		}
		traceID, err := decodeOptionalTraceID(record.TraceID)
		if err != nil {
			return plog.NewLogs(), fmt.Errorf("decode log trace id: %w", err)
		}
		if traceID != ([16]byte{}) {
			logRecord.SetTraceID(traceID)
		}
		spanID, err := decodeOptionalSpanID(record.SpanID)
		if err != nil {
			return plog.NewLogs(), fmt.Errorf("decode log span id: %w", err)
		}
		if spanID != ([8]byte{}) {
			logRecord.SetSpanID(spanID)
		}
	}

	return ld, nil
}

func initializeMetric(metric pmetric.Metric, point telemetrystore.MetricDataPoint) {
	switch point.Type {
	case "sum", "counter":
		sum := metric.SetEmptySum()
		sum.SetAggregationTemporality(temporalityFromString(point.Temporality))
		sum.SetIsMonotonic(point.IsMonotonic)
	case "histogram":
		hist := metric.SetEmptyHistogram()
		hist.SetAggregationTemporality(temporalityFromString(point.Temporality))
	case "summary":
		metric.SetEmptySummary()
	case "exponential_histogram":
		exp := metric.SetEmptyExponentialHistogram()
		exp.SetAggregationTemporality(temporalityFromString(point.Temporality))
	default:
		metric.SetEmptyGauge()
	}
}

func populateNumberDataPoint(dp pmetric.NumberDataPoint, point telemetrystore.MetricDataPoint) {
	dp.SetTimestamp(pcommon.NewTimestampFromTime(point.Timestamp))
	if !point.StartTime.IsZero() {
		dp.SetStartTimestamp(pcommon.NewTimestampFromTime(point.StartTime))
	}
	dp.SetDoubleValue(point.Value)
	dp.SetFlags(pmetric.DataPointFlags(point.Flags))
	_ = setMapValues(dp.Attributes(), point.Attributes)
}

func populateHistogramDataPoint(dp pmetric.HistogramDataPoint, point telemetrystore.MetricDataPoint) {
	dp.SetTimestamp(pcommon.NewTimestampFromTime(point.Timestamp))
	if !point.StartTime.IsZero() {
		dp.SetStartTimestamp(pcommon.NewTimestampFromTime(point.StartTime))
	}
	dp.SetCount(point.Count)
	dp.SetSum(point.Sum)
	dp.SetMin(point.Min)
	dp.SetMax(point.Max)
	dp.SetFlags(pmetric.DataPointFlags(point.Flags))
	dp.BucketCounts().FromRaw(point.BucketCounts)
	dp.ExplicitBounds().FromRaw(point.ExplicitBounds)
	_ = setMapValues(dp.Attributes(), point.Attributes)
}

func populateSummaryDataPoint(dp pmetric.SummaryDataPoint, point telemetrystore.MetricDataPoint) {
	dp.SetTimestamp(pcommon.NewTimestampFromTime(point.Timestamp))
	if !point.StartTime.IsZero() {
		dp.SetStartTimestamp(pcommon.NewTimestampFromTime(point.StartTime))
	}
	dp.SetCount(point.Count)
	dp.SetSum(point.Sum)
	dp.SetFlags(pmetric.DataPointFlags(point.Flags))
	quantiles := dp.QuantileValues()
	for _, quantile := range point.Quantiles {
		qv := quantiles.AppendEmpty()
		qv.SetQuantile(quantile.Quantile)
		qv.SetValue(quantile.Value)
	}
	_ = setMapValues(dp.Attributes(), point.Attributes)
}

func populateExpHistogramDataPoint(dp pmetric.ExponentialHistogramDataPoint, point telemetrystore.MetricDataPoint) {
	dp.SetTimestamp(pcommon.NewTimestampFromTime(point.Timestamp))
	if !point.StartTime.IsZero() {
		dp.SetStartTimestamp(pcommon.NewTimestampFromTime(point.StartTime))
	}
	dp.SetCount(point.Count)
	dp.SetSum(point.Sum)
	dp.SetMin(point.Min)
	dp.SetMax(point.Max)
	dp.SetScale(0)
	dp.SetZeroCount(0)
	dp.Positive().SetOffset(0)
	dp.Negative().SetOffset(0)
	dp.SetFlags(pmetric.DataPointFlags(point.Flags))
	_ = setMapValues(dp.Attributes(), point.Attributes)
}

func getOrAppendResourceSpans(items ptrace.ResourceSpansSlice, cache map[string]ptrace.ResourceSpans, resource telemetrystore.Resource) (ptrace.ResourceSpans, error) {
	key := resourceKey(resource)
	if existing, ok := cache[key]; ok {
		return existing, nil
	}
	item := items.AppendEmpty()
	if err := populateResource(item.Resource(), resource); err != nil {
		return ptrace.ResourceSpans{}, err
	}
	item.SetSchemaUrl(resource.SchemaURL)
	cache[key] = item
	return item, nil
}

func getOrAppendScopeSpans(items ptrace.ScopeSpansSlice, scope telemetrystore.Scope) ptrace.ScopeSpans {
	for i := 0; i < items.Len(); i++ {
		item := items.At(i)
		if item.Scope().Name() == scope.Name && item.Scope().Version() == scope.Version && item.SchemaUrl() == scope.SchemaURL {
			return item
		}
	}
	item := items.AppendEmpty()
	populateScope(item.Scope(), scope)
	item.SetSchemaUrl(scope.SchemaURL)
	return item
}

func getOrAppendResourceMetrics(items pmetric.ResourceMetricsSlice, cache map[string]pmetric.ResourceMetrics, resource telemetrystore.Resource) (pmetric.ResourceMetrics, error) {
	key := resourceKey(resource)
	if existing, ok := cache[key]; ok {
		return existing, nil
	}
	item := items.AppendEmpty()
	if err := populateResource(item.Resource(), resource); err != nil {
		return pmetric.ResourceMetrics{}, err
	}
	item.SetSchemaUrl(resource.SchemaURL)
	cache[key] = item
	return item, nil
}

func getOrAppendScopeMetrics(items pmetric.ScopeMetricsSlice, scope telemetrystore.Scope) pmetric.ScopeMetrics {
	for i := 0; i < items.Len(); i++ {
		item := items.At(i)
		if item.Scope().Name() == scope.Name && item.Scope().Version() == scope.Version && item.SchemaUrl() == scope.SchemaURL {
			return item
		}
	}
	item := items.AppendEmpty()
	populateScope(item.Scope(), scope)
	item.SetSchemaUrl(scope.SchemaURL)
	return item
}

func getOrAppendResourceLogs(items plog.ResourceLogsSlice, cache map[string]plog.ResourceLogs, resource telemetrystore.Resource) (plog.ResourceLogs, error) {
	key := resourceKey(resource)
	if existing, ok := cache[key]; ok {
		return existing, nil
	}
	item := items.AppendEmpty()
	if err := populateResource(item.Resource(), resource); err != nil {
		return plog.ResourceLogs{}, err
	}
	item.SetSchemaUrl(resource.SchemaURL)
	cache[key] = item
	return item, nil
}

func getOrAppendScopeLogs(items plog.ScopeLogsSlice, scope telemetrystore.Scope) plog.ScopeLogs {
	for i := 0; i < items.Len(); i++ {
		item := items.At(i)
		if item.Scope().Name() == scope.Name && item.Scope().Version() == scope.Version && item.SchemaUrl() == scope.SchemaURL {
			return item
		}
	}
	item := items.AppendEmpty()
	populateScope(item.Scope(), scope)
	item.SetSchemaUrl(scope.SchemaURL)
	return item
}

func resourceKey(resource telemetrystore.Resource) string {
	return marshalExportKey(struct {
		SchemaURL string         `json:"schemaUrl"`
		Service   string         `json:"serviceName"`
		Attrs     map[string]any `json:"attributes"`
	}{
		SchemaURL: resource.SchemaURL,
		Service:   resource.ServiceName,
		Attrs:     resourceAttributes(resource),
	})
}

func scopeKey(scope telemetrystore.Scope) telemetrystore.Scope {
	return scope
}

func metricKey(point telemetrystore.MetricDataPoint) string {
	return marshalExportKey(struct {
		Resource string `json:"resource"`
		Scope    string `json:"scope"`
		Name     string `json:"name"`
		Desc     string `json:"description"`
		Unit     string `json:"unit"`
		Type     string `json:"type"`
		Temp     string `json:"temporality"`
		Mono     bool   `json:"monotonic"`
	}{
		Resource: resourceKey(point.Resource),
		Scope:    point.Scope.Name + "|" + point.Scope.Version + "|" + point.Scope.SchemaURL,
		Name:     point.Name,
		Desc:     point.Description,
		Unit:     point.Unit,
		Type:     point.Type,
		Temp:     point.Temporality,
		Mono:     point.IsMonotonic,
	})
}

func marshalExportKey(value any) string {
	data, err := json.Marshal(value)
	if err != nil {
		panic(fmt.Sprintf("marshal export key: %v", err))
	}
	return string(data)
}

func populateResource(resource pcommon.Resource, value telemetrystore.Resource) error {
	return setMapValues(resource.Attributes(), resourceAttributes(value))
}

func populateScope(scope pcommon.InstrumentationScope, value telemetrystore.Scope) {
	scope.SetName(value.Name)
	scope.SetVersion(value.Version)
}

func resourceAttributes(resource telemetrystore.Resource) map[string]any {
	if resource.ServiceName == "" {
		return resource.Attributes
	}
	attrs := make(map[string]any, len(resource.Attributes)+1)
	for key, value := range resource.Attributes {
		attrs[key] = value
	}
	if _, ok := attrs["service.name"]; !ok {
		attrs["service.name"] = resource.ServiceName
	}
	return attrs
}

func setMapValues(dest pcommon.Map, values map[string]any) error {
	for key, value := range values {
		if err := setValue(dest.PutEmpty(key), value); err != nil {
			return fmt.Errorf("attribute %q: %w", key, err)
		}
	}
	return nil
}

func setValue(dest pcommon.Value, value any) error {
	switch v := value.(type) {
	case nil:
		dest.SetEmptyBytes()
	case string:
		dest.SetStr(v)
	case bool:
		dest.SetBool(v)
	case int:
		dest.SetInt(int64(v))
	case int8:
		dest.SetInt(int64(v))
	case int16:
		dest.SetInt(int64(v))
	case int32:
		dest.SetInt(int64(v))
	case int64:
		dest.SetInt(v)
	case uint:
		dest.SetInt(int64(v))
	case uint8:
		dest.SetInt(int64(v))
	case uint16:
		dest.SetInt(int64(v))
	case uint32:
		dest.SetInt(int64(v))
	case uint64:
		dest.SetInt(int64(v))
	case float32:
		dest.SetDouble(float64(v))
	case float64:
		dest.SetDouble(v)
	case []byte:
		dest.SetEmptyBytes().FromRaw(v)
	case []any:
		arr := dest.SetEmptySlice()
		for _, item := range v {
			if err := setValue(arr.AppendEmpty(), item); err != nil {
				return err
			}
		}
	case []string:
		arr := dest.SetEmptySlice()
		for _, item := range v {
			arr.AppendEmpty().SetStr(item)
		}
	case []int:
		arr := dest.SetEmptySlice()
		for _, item := range v {
			arr.AppendEmpty().SetInt(int64(item))
		}
	case []float64:
		arr := dest.SetEmptySlice()
		for _, item := range v {
			arr.AppendEmpty().SetDouble(item)
		}
	case map[string]any:
		kv := dest.SetEmptyMap()
		return setMapValues(kv, v)
	default:
		return fmt.Errorf("unsupported attribute type %T", value)
	}
	return nil
}

func decodeTraceID(value string) (pcommon.TraceID, error) {
	var id pcommon.TraceID
	decoded, err := hex.DecodeString(value)
	if err != nil {
		return id, err
	}
	if len(decoded) != len(id) {
		return id, fmt.Errorf("expected 16 bytes, got %d", len(decoded))
	}
	copy(id[:], decoded)
	return id, nil
}

func decodeOptionalTraceID(value string) (pcommon.TraceID, error) {
	if value == "" {
		return pcommon.TraceID{}, nil
	}
	return decodeTraceID(value)
}

func decodeSpanID(value string) (pcommon.SpanID, error) {
	var id pcommon.SpanID
	decoded, err := hex.DecodeString(value)
	if err != nil {
		return id, err
	}
	if len(decoded) != len(id) {
		return id, fmt.Errorf("expected 8 bytes, got %d", len(decoded))
	}
	copy(id[:], decoded)
	return id, nil
}

func decodeOptionalSpanID(value string) (pcommon.SpanID, error) {
	if value == "" {
		return pcommon.SpanID{}, nil
	}
	return decodeSpanID(value)
}

func spanKindFromString(value string) ptrace.SpanKind {
	switch value {
	case "INTERNAL":
		return ptrace.SpanKindInternal
	case "SERVER":
		return ptrace.SpanKindServer
	case "CLIENT":
		return ptrace.SpanKindClient
	case "PRODUCER":
		return ptrace.SpanKindProducer
	case "CONSUMER":
		return ptrace.SpanKindConsumer
	default:
		return ptrace.SpanKindUnspecified
	}
}

func statusCodeFromString(value string) ptrace.StatusCode {
	switch value {
	case "OK":
		return ptrace.StatusCodeOk
	case "ERROR":
		return ptrace.StatusCodeError
	default:
		return ptrace.StatusCodeUnset
	}
}

func temporalityFromString(value string) pmetric.AggregationTemporality {
	switch value {
	case "delta":
		return pmetric.AggregationTemporalityDelta
	case "cumulative":
		return pmetric.AggregationTemporalityCumulative
	default:
		return pmetric.AggregationTemporalityUnspecified
	}
}
