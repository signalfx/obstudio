import static org.junit.jupiter.api.Assertions.*;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.TraceFlags;
import io.opentelemetry.api.trace.TraceState;
import io.opentelemetry.context.Scope;
import io.opentelemetry.exporter.otlp.http.logs.OtlpHttpLogRecordExporter;
import io.opentelemetry.instrumentation.logback.appender.v1_0.OpenTelemetryAppender;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.common.export.RetryPolicy;
import io.opentelemetry.sdk.logs.SdkLoggerProvider;
import io.opentelemetry.sdk.logs.export.SimpleLogRecordProcessor;
import io.opentelemetry.sdk.testing.exporter.InMemoryLogRecordExporter;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

@Timeout(5)
class LoggingWireTest {
  String base;
  String origin;
  String key;
  InMemoryLogRecordExporter memory;
  SdkLoggerProvider provider;
  LoggerContext logContext;
  Logger logger;
  ListAppender<ILoggingEvent> sink;
  final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();

  @BeforeEach void setup() {
    base = System.getenv("LOGGING_CONTRACT_RECEIVER_URL");
    Assumptions.assumeTrue(base != null, "Use run_logging_contract.py for the owned loopback receiver");
    assertEquals("127.0.0.1", URI.create(base).getHost());
    origin = base.substring(0, base.lastIndexOf('/'));
    key = base.substring(base.lastIndexOf('/') + 1);
    memory = InMemoryLogRecordExporter.create();
    provider = SdkLoggerProvider.builder().addLogRecordProcessor(SimpleLogRecordProcessor.create(memory)).build();
    logContext = new LoggerContext();
    logContext.setMDCAdapter(new ch.qos.logback.classic.util.LogbackMDCAdapter());
    logContext.start();
    logger = logContext.getLogger("logging-wire");
    logger.setAdditive(false);
    sink = new ListAppender<>();
    sink.setContext(logContext);
    sink.start();
    logger.addAppender(sink);
    var bridge = new OpenTelemetryAppender();
    bridge.setContext(logContext);
    bridge.setOpenTelemetry(OpenTelemetrySdk.builder().setLoggerProvider(provider).build());
    bridge.start();
    logger.addAppender(bridge);
  }

  @AfterEach void cleanup() {
    if (logContext != null) { logContext.stop(); }
    if (provider != null) { provider.close(); }
  }

  JsonObject get(String path) throws Exception {
    var request = HttpRequest.newBuilder(URI.create(origin + "/" + path)).timeout(Duration.ofSeconds(1)).GET().build();
    var response = http.send(request, HttpResponse.BodyHandlers.ofString());
    assertEquals(200, response.statusCode());
    return JsonParser.parseString(response.body()).getAsJsonObject();
  }

  void wireCase(String scenario) throws Exception {
    var callTimeout = Duration.ofMillis(scenario.equals("stall") ? 200 : 800);
    var builder = OtlpHttpLogRecordExporter.builder().setEndpoint(base + "/" + scenario + "/v1/logs")
        .setTimeout(callTimeout).setConnectTimeout(Duration.ofMillis(200));
    if (scenario.equals("stall") || scenario.equals("retry")) {
      builder.setRetryPolicy(RetryPolicy.getDefault().toBuilder().setMaxAttempts(2)
          .setInitialBackoff(Duration.ofMillis(100)).setMaxBackoff(Duration.ofMillis(100))
          .setBackoffMultiplier(1).build());
    }
    try (var exporter = builder.build()) {
      int expected = scenario.equals("stall") || scenario.equals("retry") ? 1 : 3;
      var span = Span.wrap(SpanContext.create("11".repeat(16), "22".repeat(8), TraceFlags.getDefault(), TraceState.getDefault()));
      try (Scope ignored = span.makeCurrent()) {
        for (int i = 0; i < expected; i++) { logger.error("wire-{}", i); }
      }
      long started = System.nanoTime();
      var batch = memory.getFinishedLogRecordItems();
      var result = exporter.export(batch);
      result.join(1, TimeUnit.SECONDS);
      assertTrue(System.nanoTime() - started < TimeUnit.SECONDS.toNanos(1));
      var receipt = get("evidence/" + key + "/" + scenario);
      int received = receipt.get("received").getAsInt();
      if (scenario.equals("retry")) {
        assertEquals(2, received);
        assertEquals(2, receipt.get("requests").getAsInt());
      } else if (scenario.equals("stall")) {
        assertTrue(received >= 1 && received <= 2);
        assertEquals(received, receipt.get("requests").getAsInt());
      } else {
        assertEquals(expected, received);
      }
      var records = receipt.getAsJsonArray("records");
      for (int i = 0; i < records.size(); i++) {
        var record = records.get(i).getAsJsonObject();
        assertEquals("wire-" + (expected == 1 ? 0 : i), record.getAsJsonObject("body").get("stringValue").getAsString());
        assertEquals("11".repeat(16), record.get("trace_id").getAsString());
        assertEquals("22".repeat(8), record.get("span_id").getAsString());
        assertEquals(0, record.get("flags").getAsInt() & 0xff);
        assertEquals(17, record.get("severity").getAsInt());
        assertEquals(batch.get(expected == 1 ? 0 : i).getTimestampEpochNanos(), record.get("timestamp_unix_nano").getAsLong());
      }
      if (scenario.equals("retry")) {
        assertTrue(result.isDone());
        assertFalse(result.isSuccess());
        assertEquals(0, receipt.get("accepted").getAsInt());
        assertEquals(0, receipt.get("rejected").getAsInt());
        assertEquals(2, receipt.get("retryable_records").getAsInt());
      } else if (scenario.equals("stall")) {
        assertTrue(result.isDone());
        assertFalse(result.isSuccess());
        assertEquals(0, receipt.get("accepted").getAsInt());
        assertEquals(received, receipt.get("pending").getAsInt());
        get("release-stall/" + key + "/" + scenario);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(1);
        do {
          receipt = get("evidence/" + key + "/" + scenario);
          if (receipt.get("pending").getAsInt() == 0) { break; }
          Thread.sleep(10);
        } while (System.nanoTime() < deadline);
        assertEquals(received, receipt.get("accepted").getAsInt());
      } else {
        assertTrue(result.isSuccess());
        assertEquals(1, receipt.get("requests").getAsInt());
        assertEquals(scenario.equals("partial") ? 1 : 3, receipt.get("accepted").getAsInt());
        assertEquals(scenario.equals("partial") ? 2 : 0, receipt.get("rejected").getAsInt());
      }
      assertEquals(expected, sink.list.size());
      logger.info("application continued");
      assertEquals("application continued", sink.list.get(expected).getFormattedMessage());
    } finally {
      if (scenario.equals("stall")) { get("release-stall/" + key + "/" + scenario); }
    }
  }

  @Test void healthyWireReceipt() throws Exception { wireCase("healthy"); }
  @Test void partialSuccessIsNotFullAcceptance() throws Exception { wireCase("partial"); }
  @Test void timedOutClientCanHaveLateAcceptance() throws Exception { wireCase("stall"); }
  @Test void retryableFailureHonorsAttemptAndWholeOperationBudget() throws Exception { wireCase("retry"); }
}
