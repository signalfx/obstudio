import static org.junit.jupiter.api.Assertions.*;

import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import io.opentelemetry.exporter.otlp.http.logs.OtlpHttpLogRecordExporter;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.instrumentation.logback.appender.v1_0.OpenTelemetryAppender;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.common.export.RetryPolicy;
import io.opentelemetry.sdk.logs.SdkLoggerProvider;
import io.opentelemetry.sdk.logs.export.BatchLogRecordProcessor;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import io.opentelemetry.sdk.trace.samplers.Sampler;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

class TraceCorrelationTest {
  @Test @Timeout(15) void realSpansJoinCallerAndExecutorLogsAtReceiver() throws Exception {
    String base = System.getenv("LOGGING_CONTRACT_RECEIVER_URL");
    Assumptions.assumeTrue(base != null, "Use run_logging_contract.py for the owned loopback receiver");
    assertEquals("127.0.0.1", URI.create(base).getHost());
    var resource = Resource.create(Attributes.of(AttributeKey.stringKey("service.name"), "java-correlation"));
    var traces = tracerProvider(base, resource, Sampler.alwaysOn());
    var off = tracerProvider(base, resource, Sampler.alwaysOff());
    var logExporter = OtlpHttpLogRecordExporter.builder().setEndpoint(base + "/correlation/v1/logs")
        .setTimeout(Duration.ofSeconds(1)).setRetryPolicy(retryPolicy()).build();
    var logs = SdkLoggerProvider.builder().setResource(resource).addLogRecordProcessor(BatchLogRecordProcessor.builder(logExporter)
        .setMaxQueueSize(128).setMaxExportBatchSize(64).setScheduleDelay(Duration.ofMinutes(1))
        .setExporterTimeout(Duration.ofSeconds(3)).build()).build();
    var sdk = OpenTelemetrySdk.builder().setTracerProvider(traces).setLoggerProvider(logs).build();
    var logContext = new LoggerContext();
    logContext.setMDCAdapter(new ch.qos.logback.classic.util.LogbackMDCAdapter());
    logContext.start();
    var logger = logContext.getLogger("correlation");
    logger.setAdditive(false);
    var sink = new ListAppender<ILoggingEvent>();
    sink.setContext(logContext);
    sink.start();
    logger.addAppender(sink);
    var bridge = new OpenTelemetryAppender();
    bridge.setContext(logContext);
    bridge.setOpenTelemetry(sdk);
    bridge.start();
    logger.addAppender(bridge);
    var executor = Executors.newFixedThreadPool(4);
    var expected = new ConcurrentHashMap<String, SpanContext>();
    var tracer = sdk.getTracer("correlation");
    try {
      var futures = new ArrayList<Future<?>>();
      for (int i = 0; i < 10; i++) {
        final int index = i;
        var parent = tracer.spanBuilder("request-" + i).startSpan();
        try (Scope ignored = parent.makeCurrent()) {
          expected.put("parent-" + i, parent.getSpanContext());
          logger.info("parent-{}", i);
          futures.add(executor.submit(Context.current().wrap(() -> {
            var child = tracer.spanBuilder("work-" + index).startSpan();
            try (Scope childScope = child.makeCurrent()) {
              expected.put("child-" + index, child.getSpanContext());
              logger.info("child-{}", index);
            } finally { child.end(); parent.end(); }
          })));
        }
      }
      for (var future : futures) { future.get(3, TimeUnit.SECONDS); }
      var unsampled = off.get("correlation").spanBuilder("unsampled").startSpan();
      var unsampledContext = unsampled.getSpanContext();
      try (Scope ignored = unsampled.makeCurrent()) {
        assertTrue(unsampledContext.isValid());
        assertFalse(unsampled.isRecording());
        assertFalse(unsampledContext.isSampled());
        logger.info("unsampled");
      } finally { unsampled.end(); }
      logger.info("outside");
      assertTrue(logs.forceFlush().join(4, TimeUnit.SECONDS).isSuccess());
      assertTrue(traces.forceFlush().join(4, TimeUnit.SECONDS).isSuccess());
      assertTrue(off.forceFlush().join(4, TimeUnit.SECONDS).isSuccess());
      var receivedLogs = receipt(base, "");
      var receivedSpans = receipt(base, "/traces");
      assertEquals(22, receivedLogs.get("accepted").getAsInt());
      assertEquals(20, receivedSpans.get("accepted").getAsInt());
      assertEquals(1, receivedLogs.get("requests").getAsInt(), "all caller/worker logs must drain in one SDK batch");
      assertEquals(1, receivedSpans.get("requests").getAsInt(), "all sampled spans must drain in one SDK batch");
      var spans = new HashMap<String, JsonObject>();
      for (var value : receivedSpans.getAsJsonArray("spans")) {
        var span = value.getAsJsonObject();
        assertNull(spans.put(span.get("trace_id").getAsString() + "/" + span.get("span_id").getAsString(), span));
      }
      var records = new HashMap<String, JsonObject>();
      for (var value : receivedLogs.getAsJsonArray("records")) {
        var record = value.getAsJsonObject();
        assertNull(records.put(record.getAsJsonObject("body").get("stringValue").getAsString(), record));
      }
      assertEquals(20, spans.size());
      assertEquals(22, records.size());
      expected.forEach((body, sc) -> {
        assertTrue(sc.isSampled());
        var record = records.get(body);
        assertEquals(sc.getTraceId(), record.get("trace_id").getAsString());
        assertEquals(sc.getSpanId(), record.get("span_id").getAsString());
        assertEquals(sc.getTraceFlags().asByte() & 0xff, record.get("flags").getAsInt() & 0xff);
        var span = spans.get(sc.getTraceId() + "/" + sc.getSpanId());
        assertNotNull(span, "log must join the exact received span");
        assertEquals("java-correlation", record.getAsJsonObject("resource").getAsJsonObject("service.name").get("stringValue").getAsString());
        assertEquals(record.get("resource"), span.get("resource"));
        if (body.startsWith("child-")) {
          var parent = expected.get(body.replace("child-", "parent-"));
          assertEquals(parent.getSpanId(), span.get("parent_span_id").getAsString());
          assertEquals(parent.getTraceId(), sc.getTraceId());
        }
      });
      var record = records.get("unsampled");
      assertEquals(unsampledContext.getTraceId(), record.get("trace_id").getAsString());
      assertEquals(unsampledContext.getSpanId(), record.get("span_id").getAsString());
      assertEquals(unsampledContext.getTraceFlags().asByte() & 0xff, record.get("flags").getAsInt() & 0xff);
      assertFalse(spans.containsKey(unsampledContext.getTraceId() + "/" + unsampledContext.getSpanId()));
      assertEquals("", records.get("outside").get("trace_id").getAsString());
      assertEquals("", records.get("outside").get("span_id").getAsString());
      assertEquals(22, sink.list.size());
    } finally {
      executor.shutdownNow();
      try {
        assertTrue(executor.awaitTermination(2, TimeUnit.SECONDS));
      } finally {
        logContext.stop();
        try { sdk.close(); } finally { off.close(); }
      }
    }
  }

  static SdkTracerProvider tracerProvider(String base, Resource resource, Sampler sampler) {
    var exporter = OtlpHttpSpanExporter.builder().setEndpoint(base + "/correlation/v1/traces")
        .setTimeout(Duration.ofSeconds(1)).setRetryPolicy(retryPolicy()).build();
    return SdkTracerProvider.builder().setResource(resource).setSampler(sampler).addSpanProcessor(BatchSpanProcessor.builder(exporter)
        .setMaxQueueSize(128).setMaxExportBatchSize(64).setScheduleDelay(Duration.ofMinutes(1))
        .setExporterTimeout(Duration.ofSeconds(3)).build()).build();
  }

  static RetryPolicy retryPolicy() {
    return RetryPolicy.getDefault().toBuilder().setMaxAttempts(2)
        .setInitialBackoff(Duration.ofMillis(100)).setMaxBackoff(Duration.ofMillis(100))
        .setBackoffMultiplier(1).build();
  }

  static JsonObject receipt(String base, String suffix) throws Exception {
    String origin = base.substring(0, base.lastIndexOf('/'));
    String key = base.substring(base.lastIndexOf('/') + 1);
    var client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
    var request = HttpRequest.newBuilder(URI.create(origin + "/evidence/" + key + "/correlation" + suffix)).timeout(Duration.ofSeconds(2)).GET().build();
    var response = client.send(request, HttpResponse.BodyHandlers.ofString());
    assertEquals(200, response.statusCode());
    return JsonParser.parseString(response.body()).getAsJsonObject();
  }
}
