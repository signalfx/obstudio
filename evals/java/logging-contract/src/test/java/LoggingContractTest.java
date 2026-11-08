import static org.junit.jupiter.api.Assertions.*;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.LoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.logs.Severity;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Scope;
import io.opentelemetry.instrumentation.logback.appender.v1_0.OpenTelemetryAppender;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.logs.LogLimits;
import io.opentelemetry.sdk.logs.SdkLoggerProvider;
import io.opentelemetry.sdk.logs.data.LogRecordData;
import io.opentelemetry.sdk.logs.export.BatchLogRecordProcessor;
import io.opentelemetry.sdk.logs.export.LogRecordExporter;
import io.opentelemetry.sdk.logs.export.SimpleLogRecordProcessor;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.testing.exporter.InMemoryLogRecordExporter;
import java.time.Duration;
import java.util.Collection;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class LoggingContractTest {
  InMemoryLogRecordExporter exporter;
  SdkLoggerProvider provider;
  LoggerContext context;
  Logger logger;
  ListAppender<ILoggingEvent> sink;

  @BeforeEach void setup() {
    exporter = InMemoryLogRecordExporter.create();
    provider = SdkLoggerProvider.builder()
        .setResource(Resource.create(Attributes.of(AttributeKey.stringKey("service.name"), "java-logging-contract")))
        .setLogLimits(() -> LogLimits.builder().setMaxNumberOfAttributes(8).setMaxAttributeValueLength(32).build())
        .addLogRecordProcessor(SimpleLogRecordProcessor.create(exporter)).build();
    context = new LoggerContext();
    context.setMDCAdapter(new ch.qos.logback.classic.util.LogbackMDCAdapter());
    context.start();
    logger = context.getLogger("contract");
    logger.setAdditive(false);
    sink = new ListAppender<>();
    sink.setContext(context);
    sink.start();
    logger.addAppender(sink);
    attachBridge(provider);
  }

  void attachBridge(SdkLoggerProvider owner) {
    OpenTelemetryAppender bridge = new OpenTelemetryAppender();
    bridge.setContext(context);
    bridge.setOpenTelemetry(OpenTelemetrySdk.builder().setLoggerProvider(owner).build());
    bridge.start();
    logger.addAppender(bridge);
  }

  @AfterEach void cleanup() { context.stop(); provider.close(); }

  static Span span(String id, boolean sampled) {
    return Span.wrap(SpanContext.create(id.repeat(32), id.repeat(16), sampled ? TraceFlags.getSampled() : TraceFlags.getDefault(), TraceState.getDefault()));
  }

  @Test void severityTimestampAndSink() {
    LoggingEvent event = new LoggingEvent(getClass().getName(), logger, Level.ERROR, "failed", null, null);
    event.setTimeStamp(1730000000125L);
    logger.callAppenders(event);
    LogRecordData r = exporter.getFinishedLogRecordItems().get(0);
    assertEquals(Severity.ERROR, r.getSeverity());
    assertEquals(1730000000125000000L, r.getTimestampEpochNanos());
    assertTrue(r.getObservedTimestampEpochNanos() > r.getTimestampEpochNanos());
    assertEquals("java-logging-contract", r.getResource().getAttribute(AttributeKey.stringKey("service.name")));
    assertEquals(1, sink.list.size());
  }

  @Test void sampledUnsampledAndDetached() {
    for (boolean sampled : new boolean[]{false, true}) {
      try (Scope ignored = span("1", sampled).makeCurrent()) { logger.error("inside"); }
    }
    logger.info("outside");
    var records = exporter.getFinishedLogRecordItems();
    assertEquals(3, records.size());
    for (int i = 0; i < 2; i++) {
      assertEquals("1".repeat(32), records.get(i).getSpanContext().getTraceId());
      assertEquals("1".repeat(16), records.get(i).getSpanContext().getSpanId());
      assertEquals(i == 1, records.get(i).getSpanContext().isSampled());
    }
    assertFalse(records.get(2).getSpanContext().isValid());
  }

  @Test void concurrentContextIsolation() {
    CompletableFuture.allOf(CompletableFuture.runAsync(() -> {
      try (Scope ignored = span("3", true).makeCurrent()) { logger.info("3"); }
    }), CompletableFuture.runAsync(() -> {
      try (Scope ignored = span("4", true).makeCurrent()) { logger.info("4"); }
    })).join();
    var records = exporter.getFinishedLogRecordItems();
    assertEquals(2, records.size());
    for (var r : records) { assertEquals(r.getBody().asString().repeat(32), r.getSpanContext().getTraceId()); }
  }

  @Test void limitsAndExplicitPrivacyPolicy() {
    provider.get("policy").logRecordBuilder().setBody("request failed")
        .setAttribute("exception.type", "ValueError").emit();
    var safe = exporter.getFinishedLogRecordItems().get(0);
    assertEquals("ValueError", safe.getAttributes().get(AttributeKey.stringKey("exception.type")));
    assertNull(safe.getAttributes().get(AttributeKey.stringKey("exception.message")));
    assertNull(safe.getAttributes().get(AttributeKey.stringKey("exception.stacktrace")));
    var builder = provider.get("limits").logRecordBuilder().setBody("x".repeat(400));
    for (int i = 0; i < 20; i++) { builder.setAttribute("k" + i, "v".repeat(100)); }
    builder.emit();
    var limited = exporter.getFinishedLogRecordItems().get(1);
    assertEquals(8, limited.getAttributes().size());
    assertEquals(20, limited.getTotalAttributeCount());
    limited.getAttributes().forEach((k, v) -> assertEquals(32, ((String) v).length()));
    assertEquals(400, limited.getBody().asString().length());
  }

  @Test void exportFailureIsBoundedWithSinkPreserved() {
    AtomicInteger calls = new AtomicInteger();
    LogRecordExporter failed = new LogRecordExporter() {
      public CompletableResultCode export(Collection<LogRecordData> records) { calls.incrementAndGet(); return CompletableResultCode.ofFailure(); }
      public CompletableResultCode flush() { return CompletableResultCode.ofSuccess(); }
      public CompletableResultCode shutdown() { return CompletableResultCode.ofSuccess(); }
    };
    var failedProvider = SdkLoggerProvider.builder().addLogRecordProcessor(BatchLogRecordProcessor.builder(failed)
        .setMaxQueueSize(8).setMaxExportBatchSize(8).setExporterTimeout(Duration.ofMillis(100)).build()).build();
    logger.detachAppender(sink);
    logger.detachAndStopAllAppenders();
    logger.addAppender(sink);
    attachBridge(failedProvider);
    assertTimeoutPreemptively(Duration.ofSeconds(3), () -> {
      logger.error("receiver unavailable");
      failedProvider.forceFlush().join(1, TimeUnit.SECONDS);
      failedProvider.shutdown().join(1, TimeUnit.SECONDS);
    });
    assertEquals(1, calls.get());
    assertEquals(1, sink.list.size());
    assertEquals(0, exporter.getFinishedLogRecordItems().size());
  }

  @Test void explicitBridgeOptOutKeepsOriginalSink() {
    logger.detachAppender(sink);
    logger.detachAndStopAllAppenders();
    logger.addAppender(sink);
    logger.error("disabled");
    assertEquals(0, exporter.getFinishedLogRecordItems().size());
    assertEquals(1, sink.list.size());
  }
}
