package kvstore

import (
	"context"
	"sync"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	otellog "go.opentelemetry.io/otel/log"
	logglobal "go.opentelemetry.io/otel/log/global"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"
)

var (
	now = time.Now

	storeTracer = otel.Tracer("kvstore/store")
	storeMeter  = otel.Meter("kvstore/store")
	storeLogger = logglobal.Logger("kvstore/store")

	telemetryOnce sync.Once
	telemetryErr  error

	storePersistDuration     metric.Float64Histogram
	storePersistErrors       metric.Int64Counter
	storeEvictions           metric.Int64Counter
	storeIndexUpdateDuration metric.Float64Histogram
	storeItemsGauge          metric.Int64ObservableGauge
	storeCapacityGauge       metric.Float64ObservableGauge
	storeIndexBacklogGauge   metric.Int64ObservableGauge

	spanStatusError = codes.Error
	logSeverityWarn = otellog.SeverityWarn
)

func initTelemetry() error {
	telemetryOnce.Do(func() {
		storePersistDuration, telemetryErr = storeMeter.Float64Histogram(
			"store.persist.duration",
			metric.WithDescription("Duration of asynchronous filesystem persistence operations"),
			metric.WithUnit("s"),
		)
		if telemetryErr != nil {
			return
		}

		storePersistErrors, telemetryErr = storeMeter.Int64Counter(
			"store.persist.errors",
			metric.WithDescription("Total filesystem persistence failures"),
			metric.WithUnit("{errors}"),
		)
		if telemetryErr != nil {
			return
		}

		storeEvictions, telemetryErr = storeMeter.Int64Counter(
			"store.evictions",
			metric.WithDescription("Total in-memory LRU evictions"),
			metric.WithUnit("{evictions}"),
		)
		if telemetryErr != nil {
			return
		}

		storeIndexUpdateDuration, telemetryErr = storeMeter.Float64Histogram(
			"store.index.update.duration",
			metric.WithDescription("Duration of background search index updates"),
			metric.WithUnit("s"),
		)
		if telemetryErr != nil {
			return
		}

		storeItemsGauge, telemetryErr = storeMeter.Int64ObservableGauge(
			"store.items",
			metric.WithDescription("Current number of key/value pairs held in memory"),
			metric.WithUnit("{items}"),
		)
		if telemetryErr != nil {
			return
		}

		storeCapacityGauge, telemetryErr = storeMeter.Float64ObservableGauge(
			"store.capacity.utilization",
			metric.WithDescription("Current ratio of in-memory items to configured capacity"),
			metric.WithUnit("{ratio}"),
		)
		if telemetryErr != nil {
			return
		}

		storeIndexBacklogGauge, telemetryErr = storeMeter.Int64ObservableGauge(
			"store.index.backlog",
			metric.WithDescription("Pending index events waiting for the background worker"),
			metric.WithUnit("{events}"),
		)
	})
	return telemetryErr
}

func (s *Store) initTelemetry() error {
	if err := initTelemetry(); err != nil {
		return err
	}

	registration, err := storeMeter.RegisterCallback(
		func(_ context.Context, observer metric.Observer) error {
			snapshot := s.telemetrySnapshot()
			observer.ObserveInt64(storeItemsGauge, int64(snapshot.items))
			observer.ObserveFloat64(storeCapacityGauge, snapshot.utilization)
			observer.ObserveInt64(storeIndexBacklogGauge, int64(snapshot.backlog))
			return nil
		},
		storeItemsGauge,
		storeCapacityGauge,
		storeIndexBacklogGauge,
	)
	if err != nil {
		return err
	}

	s.telemetryRegistration = registration
	return nil
}

func (s *Store) shutdownTelemetry() {
	registration, ok := s.telemetryRegistration.(metric.Registration)
	if ok {
		_ = registration.Unregister()
	}
}

type telemetrySnapshot struct {
	items       int
	backlog     int
	utilization float64
}

func (s *Store) telemetrySnapshot() telemetrySnapshot {
	s.mu.RLock()
	items := len(s.items)
	capacity := s.capacity
	s.mu.RUnlock()

	snapshot := telemetrySnapshot{
		items:   items,
		backlog: len(s.indexCh),
	}
	if capacity > 0 {
		snapshot.utilization = float64(items) / float64(capacity)
	}
	return snapshot
}

func recordPersistFailure(ctx context.Context, err error) {
	storePersistErrors.Add(ctx, 1)
}

func recordPersistFailureLog(ctx context.Context, key string, err error) {
	recordLog(ctx, "store.persist.failure", otellog.SeverityError, "failed persisting key to disk",
		otellog.String("store.key", key),
		otellog.String("error.message", err.Error()),
	)
}

func recordLoadSkippedLog(ctx context.Context, eventName string, severity otellog.Severity, key string, err error) {
	recordLog(ctx, eventName, severity, "skipping persisted key during startup",
		otellog.String("store.key", key),
		otellog.String("error.message", err.Error()),
	)
}

func recordLog(ctx context.Context, eventName string, severity otellog.Severity, body string, attrs ...otellog.KeyValue) {
	record := otellog.Record{}
	record.SetEventName(eventName)
	record.SetTimestamp(now())
	record.SetObservedTimestamp(now())
	record.SetSeverity(severity)
	record.SetSeverityText(severity.String())
	record.SetBody(otellog.StringValue(body))
	record.AddAttributes(attrs...)
	storeLogger.Emit(ctx, record)
}

func recordPersistSpanError(span trace.Span, err error) {
	span.RecordError(err)
	span.SetStatus(spanStatusError, "persist failed")
	span.SetAttributes(attribute.String("error.message", err.Error()))
}
