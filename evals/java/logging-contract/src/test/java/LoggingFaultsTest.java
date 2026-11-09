import static org.junit.jupiter.api.Assertions.*;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.instrumentation.logback.appender.v1_0.OpenTelemetryAppender;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.common.CompletableResultCode;
import io.opentelemetry.sdk.logs.SdkLoggerProvider;
import io.opentelemetry.sdk.logs.data.LogRecordData;
import io.opentelemetry.sdk.logs.export.BatchLogRecordProcessor;
import io.opentelemetry.sdk.logs.export.LogRecordExporter;
import io.opentelemetry.sdk.logs.export.SimpleLogRecordProcessor;
import io.opentelemetry.sdk.testing.exporter.InMemoryLogRecordExporter;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

@Timeout(5)
class LoggingFaultsTest {
  InMemoryLogRecordExporter memory;
  SdkLoggerProvider provider;
  LoggerContext logContext;
  Logger logger;
  OpenTelemetryAppender bridge;
  ListAppender<ILoggingEvent> sink;

  @BeforeEach void setup() {
    logContext = new LoggerContext();
    logContext.setMDCAdapter(new ch.qos.logback.classic.util.LogbackMDCAdapter());
    logContext.start();
    logger = logContext.getLogger("logging-fault");
    logger.setAdditive(false);
    sink = new ListAppender<>() {
      @Override protected void append(ILoggingEvent event) {
        event.prepareForDeferredProcessing();
        super.append(event);
      }
    };
    sink.setContext(logContext);
    sink.start();
    logger.addAppender(sink);
    memory = InMemoryLogRecordExporter.create();
    useExporter(memory, false);
  }

  void useExporter(LogRecordExporter exporter, boolean batch) {
    if (bridge != null) {
      logger.detachAppender(bridge);
      bridge.stop();
      provider.close();
    }
    var builder = SdkLoggerProvider.builder();
    if (batch) {
      builder.addLogRecordProcessor(BatchLogRecordProcessor.builder(exporter)
          .setMaxQueueSize(8).setMaxExportBatchSize(8)
          .setScheduleDelay(Duration.ofMinutes(1)).setExporterTimeout(Duration.ofSeconds(2)).build());
    } else {
      builder.addLogRecordProcessor(SimpleLogRecordProcessor.create(exporter));
    }
    provider = builder.build();
    bridge = new OpenTelemetryAppender();
    bridge.setContext(logContext);
    bridge.setCaptureKeyValuePairAttributes(true);
    bridge.setCaptureMdcAttributes("request.id");
    bridge.setOpenTelemetry(OpenTelemetrySdk.builder().setLoggerProvider(provider).build());
    bridge.start();
    logger.addAppender(bridge);
  }

  @AfterEach void cleanup() {
    logContext.stop();
    provider.close();
  }

  void logFailure(Throwable error, Map<String, Object> fields) {
    // Fixture-owned policy: allowlisted MDC, fixed category and type only.
    var mdc = logContext.getMDCAdapter();
    var previous = mdc.getCopyOfContextMap();
    mdc.setContextMap(Map.of("request.id", (String) fields.get("request.id")));
    try {
      logger.atError().addKeyValue("exception.type", error.getClass().getName()).log("request failed");
    } finally {
      if (previous == null) { mdc.clear(); } else { mdc.setContextMap(previous); }
    }
  }

  @Test void realExceptionMinimizedBeforeBridgeAndOriginalSink() {
    String canary = "password=synthetic-private-canary";
    var error = new IllegalStateException(canary, new IllegalArgumentException(canary));
    var fields = Map.<String, Object>of("request.id", "request-1", "payload", Map.of("token", canary), "error.kind", error.getClass().getName());
    var mdc = logContext.getMDCAdapter();
    mdc.put("private.token", canary);
    try {
      logger.atError().setCause(error).addKeyValue("error.kind", fields.get("error.kind")).log("unsafe control");
      var unsafe = memory.getFinishedLogRecordItems().get(0);
      assertEquals(canary, unsafe.getAttributes().get(AttributeKey.stringKey("exception.message")));
      assertTrue(unsafe.getAttributes().get(AttributeKey.stringKey("exception.stacktrace")).contains(canary));
      assertEquals(error.getClass().getName(), unsafe.getAttributes().get(AttributeKey.stringKey("error.kind")));
      assertEquals(canary, sink.list.get(0).getThrowableProxy().getMessage());
      logFailure(error, fields);
      var safe = memory.getFinishedLogRecordItems().get(1);
      assertEquals(error.getClass().getName(), safe.getAttributes().get(AttributeKey.stringKey("exception.type")));
      assertEquals("request-1", safe.getAttributes().get(AttributeKey.stringKey("request.id")));
      assertEquals("request failed", safe.getBody().asString());
      for (String key : List.of("exception.message", "exception.stacktrace", "payload", "private.token", "error.kind")) {
        assertNull(safe.getAttributes().get(AttributeKey.stringKey(key)));
      }
      assertFalse(safe.getAttributes().toString().contains(canary));
      assertNull(sink.list.get(1).getThrowableProxy());
      assertEquals(Map.of("request.id", "request-1"), sink.list.get(1).getMDCPropertyMap());
      assertEquals(canary, mdc.get("private.token"), "producer must restore prior caller MDC");
    } finally { mdc.clear(); }
  }

  static class BlockingExporter implements LogRecordExporter {
    final CountDownLatch entered = new CountDownLatch(1);
    final CountDownLatch release = new CountDownLatch(1);
    final List<String> bodies = new ArrayList<>();
    final AtomicInteger maximumBatch = new AtomicInteger();

    public CompletableResultCode export(Collection<LogRecordData> records) {
      entered.countDown();
      try {
        if (!release.await(2, TimeUnit.SECONDS)) { return CompletableResultCode.ofFailure(); }
      } catch (InterruptedException error) {
        Thread.currentThread().interrupt();
        return CompletableResultCode.ofFailure();
      }
      maximumBatch.accumulateAndGet(records.size(), Math::max);
      for (var record : records) { bodies.add(record.getBody().asString()); }
      return CompletableResultCode.ofSuccess();
    }
    public CompletableResultCode flush() { return CompletableResultCode.ofSuccess(); }
    public CompletableResultCode shutdown() { release.countDown(); return CompletableResultCode.ofSuccess(); }
  }

  @Test void overloadBoundsBatchesAndExposesLocalLoss() throws Exception {
    var exporter = new BlockingExporter();
    useExporter(exporter, true);
    int attempted = 48;
    try {
      for (int i = 0; i < 8; i++) { logger.info("record-{}", i); }
      assertTrue(exporter.entered.await(2, TimeUnit.SECONDS));
      for (int i = 8; i < attempted; i++) { logger.info("record-{}", i); }
      assertEquals(attempted, sink.list.size());
    } finally { exporter.release.countDown(); }
    var flushed = provider.forceFlush();
    flushed.join(2, TimeUnit.SECONDS);
    assertTrue(flushed.isSuccess());
    int exported = exporter.bodies.size();
    assertTrue(exported >= 8 && exported < attempted);
    assertEquals(exported, new HashSet<>(exporter.bodies).size());
    assertTrue(exporter.maximumBatch.get() <= 8);
    int inferredLocalDrops = attempted - exported;
    assertTrue(inferredLocalDrops > 0);
  }

  @Test void sdkFailureDiagnosticsVisibleOutsideApplicationBridge() throws Exception {
    var diagnostics = java.util.logging.Logger.getLogger("io.opentelemetry.sdk");
    var previousLevel = diagnostics.getLevel();
    boolean previousParents = diagnostics.getUseParentHandlers();
    var observed = new CountDownLatch(1);
    var diagnosticCount = new AtomicInteger();
    Handler handler = new Handler() {
      public void publish(LogRecord record) {
        if (record.getMessage().contains("Exporter failed")) {
          diagnosticCount.incrementAndGet();
          observed.countDown();
        }
      }
      public void flush() {}
      public void close() {}
    };
    diagnostics.addHandler(handler);
    diagnostics.setLevel(Level.ALL);
    diagnostics.setUseParentHandlers(false);
    var calls = new AtomicInteger();
    LogRecordExporter failed = new LogRecordExporter() {
      public CompletableResultCode export(Collection<LogRecordData> records) {
        calls.incrementAndGet();
        return CompletableResultCode.ofFailure();
      }
      public CompletableResultCode flush() { return CompletableResultCode.ofSuccess(); }
      public CompletableResultCode shutdown() { return CompletableResultCode.ofSuccess(); }
    };
    try {
      useExporter(failed, true);
      for (int i = 0; i < 8; i++) { logger.error("first failure"); }
      assertTrue(observed.await(2, TimeUnit.SECONDS), "SDK diagnostic must be visible");
      logger.info("application continued");
      provider.forceFlush().join(2, TimeUnit.SECONDS);
      assertEquals(2, calls.get());
      assertTrue(diagnosticCount.get() >= 1 && diagnosticCount.get() <= 2);
      assertEquals(9, sink.list.size());
      assertEquals("application continued", sink.list.get(8).getFormattedMessage());
    } finally {
      diagnostics.removeHandler(handler);
      diagnostics.setLevel(previousLevel);
      diagnostics.setUseParentHandlers(previousParents);
    }
  }
}
