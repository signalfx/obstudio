import static org.junit.jupiter.api.Assertions.*;

import ch.qos.logback.classic.AsyncAppender;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import io.opentelemetry.api.logs.Severity;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import io.opentelemetry.instrumentation.logback.appender.v1_0.OpenTelemetryAppender;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.logs.SdkLoggerProvider;
import io.opentelemetry.sdk.logs.export.BatchLogRecordProcessor;
import io.opentelemetry.sdk.logs.export.SimpleLogRecordProcessor;
import io.opentelemetry.sdk.testing.exporter.InMemoryLogRecordExporter;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

@Timeout(5)
class AsyncLoggingTest {
  InMemoryLogRecordExporter exporter;
  SdkLoggerProvider provider;
  LoggerContext logContext;
  Logger logger;
  OpenTelemetryAppender bridge;
  ListAppender<ILoggingEvent> sink;

  @BeforeEach void setup() {
    exporter = InMemoryLogRecordExporter.create();
    provider = SdkLoggerProvider.builder().addLogRecordProcessor(SimpleLogRecordProcessor.create(exporter)).build();
    logContext = new LoggerContext();
    logContext.setMDCAdapter(new ch.qos.logback.classic.util.LogbackMDCAdapter());
    logContext.start();
    logger = logContext.getLogger("async-contract");
    logger.setAdditive(false);
    sink = new ListAppender<>(); sink.setContext(logContext); sink.start(); logger.addAppender(sink);
    bridge = bridge(provider); logger.addAppender(bridge);
  }

  OpenTelemetryAppender bridge(SdkLoggerProvider owner) {
    var b = new OpenTelemetryAppender(); b.setContext(logContext);
    b.setCaptureMdcAttributes("request.id");
    b.setOpenTelemetry(OpenTelemetrySdk.builder().setLoggerProvider(owner).build()); b.start(); return b;
  }
  @AfterEach void cleanup() { logContext.stop(); provider.close(); }
  static String tid(int id) { return String.format("%032x", id); }
  static String sid(int id) { return String.format("%016x", id + 100); }
  static Span span(int id, int flags) { return Span.wrap(SpanContext.create(tid(id), sid(id), TraceFlags.fromByte((byte) flags), TraceState.getDefault())); }
  record Wanted(int id, int flags) {}

  void expect(Map<String, Wanted> wanted) {
    var records = exporter.getFinishedLogRecordItems(); assertEquals(wanted.size(), records.size());
    var seen = new HashSet<String>();
    for (var r : records) {
      var body = r.getBody().asString(); assertTrue(seen.add(body), "duplicate " + body);
      var w = wanted.get(body); assertNotNull(w, body); var actual = r.getSpanContext();
      assertEquals(w.id() == 0 ? "0".repeat(32) : tid(w.id()), actual.getTraceId(), body);
      assertEquals(w.id() == 0 ? "0".repeat(16) : sid(w.id()), actual.getSpanId(), body);
      assertEquals(w.flags(), actual.getTraceFlags().asByte(), body);
      assertEquals(Severity.INFO, r.getSeverity());
    }
  }
  static void waitFor(CountDownLatch latch) {
    try { assertTrue(latch.await(2, TimeUnit.SECONDS), "worker deadline"); }
    catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new RuntimeException(e); }
  }
  static ExecutorService pool(int threads) throws Exception {
    var executor = Executors.newFixedThreadPool(threads);
    executor.submit(() -> {}).get(2, TimeUnit.SECONDS); return executor;
  }
  static void stop(ExecutorService executor) throws Exception {
    executor.shutdownNow(); assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS));
  }

  @Test void parentCapturedBeforeCompletableFutureAndCallbackHandoff() throws Exception {
    var executor = pool(1); var gate = new CountDownLatch(1);
    try {
      var futures = new ArrayList<CompletableFuture<Void>>(); var expected = new HashMap<String, Wanted>();
      for (int flags = 0; flags < 2; flags++) {
        final int f = flags;
        try (Scope ignored = span(11 + f, f).makeCurrent()) {
          Context captured = Context.current();
          var future = CompletableFuture.runAsync(captured.wrap(() -> { waitFor(gate); logger.info("task-" + f); }), executor);
          futures.add(future.thenRunAsync(captured.wrap(() -> logger.info("callback-" + f)), executor));
        }
        expected.put("task-" + f, new Wanted(11 + f, f)); expected.put("callback-" + f, new Wanted(11 + f, f));
      }
      logger.info("outside"); expected.put("outside", new Wanted(0, 0)); gate.countDown();
      CompletableFuture.allOf(futures.toArray(new CompletableFuture<?>[0])).get(2, TimeUnit.SECONDS); expect(expected);
    } finally { gate.countDown(); stop(executor); }
  }

  @Test void twentyConcurrentParentsMatchExactRecordContext() throws Exception {
    logger.detachAndStopAllAppenders(); provider.close(); exporter = InMemoryLogRecordExporter.create();
    provider = SdkLoggerProvider.builder().addLogRecordProcessor(BatchLogRecordProcessor.builder(exporter).setScheduleDelay(Duration.ofMinutes(1)).build()).build();
    logger.addAppender(bridge(provider));
    var executor = pool(4); var gate = new CountDownLatch(1);
    try {
      var futures = new ArrayList<CompletableFuture<Void>>(); var expected = new HashMap<String, Wanted>();
      for (int id = 1; id <= 20; id++) {
        final int value = id;
        try (Scope ignored = span(value, value % 2).makeCurrent()) {
          futures.add(CompletableFuture.runAsync(Context.current().wrap(() -> { waitFor(gate); logger.info("task-" + value); }), executor));
        }
        expected.put("task-" + value, new Wanted(value, value % 2));
      }
      gate.countDown(); CompletableFuture.allOf(futures.toArray(new CompletableFuture<?>[0])).get(2, TimeUnit.SECONDS);
      var flushed = provider.forceFlush(); flushed.join(2, TimeUnit.SECONDS); assertTrue(flushed.isSuccess());
      expect(expected);
    } finally { gate.countDown(); stop(executor); }
  }

  @Test void reusedWorkerAndErrorCleanupWithUnwrappedNegativeControl() throws Exception {
    var executor = pool(1);
    try {
      try (Scope ignored = span(31, 1).makeCurrent()) {
        executor.submit(() -> logger.info("raw-executor")).get(2, TimeUnit.SECONDS);
        executor.submit(Context.current().wrap(() -> logger.info("wrapped-executor"))).get(2, TimeUnit.SECONDS);
        var failed = executor.submit(Context.current().wrap(() -> { try { throw new IllegalStateException("synthetic failure"); } finally { logger.info("error-cleanup"); } }));
        assertThrows(ExecutionException.class, () -> failed.get(2, TimeUnit.SECONDS));
      }
      executor.submit(() -> logger.info("reused-clean")).get(2, TimeUnit.SECONDS);
      expect(Map.of("raw-executor", new Wanted(0, 0), "wrapped-executor", new Wanted(31, 1), "error-cleanup", new Wanted(31, 1), "reused-clean", new Wanted(0, 0)));
    } finally { stop(executor); }
  }

  @Test void cancellationRestoresReusedWorkerContext() throws Exception {
    var executor = pool(1); var entered = new CountDownLatch(1); var cleaned = new CountDownLatch(1);
    try {
      java.util.concurrent.Future<?> future;
      try (Scope ignored = span(41, 1).makeCurrent()) {
        future = executor.submit(Context.current().wrap(() -> {
          try { entered.countDown(); new CountDownLatch(1).await(); }
          catch (InterruptedException e) { Thread.currentThread().interrupt(); }
          finally { logger.info("cancel-cleanup"); cleaned.countDown(); }
        }));
      }
      waitFor(entered); assertTrue(future.cancel(true)); waitFor(cleaned);
      executor.submit(() -> logger.info("outside-after-cancel")).get(2, TimeUnit.SECONDS);
      expect(Map.of("cancel-cleanup", new Wanted(41, 1), "outside-after-cancel", new Wanted(0, 0)));
    } finally { stop(executor); }
  }

  @Test void batchExportUsesEmitContextAfterCallerDetach() {
    logger.detachAndStopAllAppenders(); provider.close(); exporter = InMemoryLogRecordExporter.create();
    provider = SdkLoggerProvider.builder().addLogRecordProcessor(BatchLogRecordProcessor.builder(exporter).setScheduleDelay(Duration.ofMinutes(1)).build()).build();
    logger.addAppender(bridge(provider));
    try (Scope ignored = span(51, 0).makeCurrent()) { logger.info("queued"); }
    try (Scope ignored = span(99, 1).makeCurrent()) {
      var flushed = provider.forceFlush(); flushed.join(2, TimeUnit.SECONDS); assertTrue(flushed.isSuccess());
    }
    expect(Map.of("queued", new Wanted(51, 0)));
  }

  AsyncAppender asyncSink() {
    var async = new AsyncAppender(); async.setContext(logContext); async.setName("async-sink");
    async.setQueueSize(64); async.setDiscardingThreshold(0); async.setMaxFlushTime(2000); return async;
  }

  @Test void standaloneBridgeBehindAsyncAppenderIsMissingContextControl() {
    logger.detachAppender(bridge); var async = asyncSink(); async.addAppender(bridge); async.start(); logger.addAppender(async);
    var mdc = logContext.getMDCAdapter(); mdc.put("request.id", "request-61");
    try (Scope ignored = span(61, 1).makeCurrent()) { logger.info("async-before-bridge"); }
    finally { mdc.remove("request.id"); }
    async.stop();
    expect(Map.of("async-before-bridge", new Wanted(0, 0)));
    assertEquals("request-61", exporter.getFinishedLogRecordItems().get(0).getAttributes().get(AttributeKey.stringKey("request.id")));
  }

  @Test void callerThreadBridgeBesideAsyncSinkPreservesContext() {
    logger.detachAppender(sink); var async = asyncSink(); async.addAppender(sink); async.start(); logger.addAppender(async);
    try (Scope ignored = span(62, 1).makeCurrent()) { logger.info("bridge-before-async-sink"); }
    async.stop();
    expect(Map.of("bridge-before-async-sink", new Wanted(62, 1))); assertEquals(1, sink.list.size());
  }

  @Test void mdcNeedsSeparateHandoffAndRestorationOnReusedWorker() throws Exception {
    var executor = pool(1); var mdc = logContext.getMDCAdapter();
    try {
      Context captured; Map<String, String> snapshot;
      mdc.put("request.id", "request-71");
      try (Scope ignored = span(71, 1).makeCurrent()) { captured = Context.current(); snapshot = mdc.getCopyOfContextMap(); }
      finally { mdc.remove("request.id"); }
      executor.submit(captured.wrap(() -> logger.info("context-only-mdc-absent"))).get(2, TimeUnit.SECONDS);
      executor.submit(captured.wrap(() -> {
        var previous = mdc.getCopyOfContextMap(); mdc.setContextMap(snapshot);
        try { logger.info("copied-mdc"); }
        finally { if (previous == null) { mdc.clear(); } else { mdc.setContextMap(previous); } }
      })).get(2, TimeUnit.SECONDS);
      executor.submit(() -> logger.info("reused-mdc-clean")).get(2, TimeUnit.SECONDS);
      expect(Map.of("context-only-mdc-absent", new Wanted(71, 1), "copied-mdc", new Wanted(71, 1), "reused-mdc-clean", new Wanted(0, 0)));
      var key = AttributeKey.stringKey("request.id");
      var records = exporter.getFinishedLogRecordItems();
      assertNull(records.get(0).getAttributes().get(key));
      assertEquals("request-71", records.get(1).getAttributes().get(key));
      assertNull(records.get(2).getAttributes().get(key));
    } finally { mdc.clear(); stop(executor); }
  }
}
