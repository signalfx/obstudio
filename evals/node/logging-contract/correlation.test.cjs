const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Writable } = require('node:stream');
const { context, logs } = require('@opentelemetry/api');
const { AsyncLocalStorageContextManager } = require('@opentelemetry/context-async-hooks');
const { LoggerProvider, BatchLogRecordProcessor } = require('@opentelemetry/sdk-logs');
const { TracerProvider, BatchSpanProcessor, AlwaysOffSampler } = require('@opentelemetry/sdk-trace');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-proto');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-proto');
const { OpenTelemetryTransportV3 } = require('@opentelemetry/winston-transport');
const winston = require('winston');

context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
after(() => { context.disable(); logs.disable(); });

test('real SDK spans join caller and async application logs at receiver', { timeout: 10000 }, async t => {
  const base = process.env.LOGGING_CONTRACT_RECEIVER_URL;
  if (!base) { t.skip('Use run_logging_contract.py for the owned loopback receiver'); return; }
  assert.equal(new URL(base).hostname, '127.0.0.1');
  const resource = resourceFromAttributes({ 'service.name': 'node-correlation' });
  const providers = [undefined, new AlwaysOffSampler()].map(sampler => new TracerProvider({
    resource, ...(sampler ? { sampler } : {}),
    spanProcessors: [new BatchSpanProcessor({
      exporter: new OTLPTraceExporter({ url: `${base}/correlation/v1/traces`, timeoutMillis: 1000 }),
      maxQueueSize: 128, maxExportBatchSize: 64, scheduledDelayMillis: 60000, exportTimeoutMillis: 3000,
    })],
  }));
  const provider = new LoggerProvider({ resource, processors: [
    new BatchLogRecordProcessor({
      exporter: new OTLPLogExporter({ url: `${base}/correlation/v1/logs`, timeoutMillis: 1000 }),
      maxQueueSize: 128, maxExportBatchSize: 64, scheduledDelayMillis: 60000, exportTimeoutMillis: 3000,
    }),
  ] });
  logs.setGlobalLoggerProvider(provider);
  const sink = [];
  const stream = new Writable({ write(chunk, _, done) { sink.push(chunk.toString()); done(); } });
  const logger = winston.createLogger({ transports: [new winston.transports.Stream({ stream }), new OpenTelemetryTransportV3()] });
  const tracer = providers[0].getTracer('correlation');
  const expected = new Map();
  try {
    await Promise.all(Array.from({ length: 10 }, (_, i) => tracer.startActiveSpan(`request-${i}`, async parent => {
      try {
        await new Promise(resolve => setImmediate(resolve));
        await tracer.startActiveSpan(`work-${i}`, async child => {
          try {
            await new Promise(resolve => setImmediate(resolve));
            expected.set(`child-${i}`, child.spanContext());
            logger.info(`child-${i}`);
          } finally { child.end(); }
        });
        expected.set(`parent-${i}`, parent.spanContext());
        logger.info(`parent-${i}`);
      } finally { parent.end(); }
    })));
    let unsampled;
    providers[1].getTracer('correlation').startActiveSpan('unsampled', span => {
      try {
        unsampled = span.spanContext();
        assert.equal(span.isRecording(), false);
        assert.equal(unsampled.traceFlags & 1, 0);
        assert.notEqual(unsampled.traceId, '0'.repeat(32));
        logger.info('unsampled');
      } finally { span.end(); }
    });
    logger.info('outside');
    await provider.forceFlush({ timeoutMillis: 4000 });
    await Promise.all(providers.map(p => p.forceFlush({ timeoutMillis: 4000 })));
    async function receipt(suffix) {
      const response = await fetch(`${new URL(base).origin}/evidence${new URL(base).pathname}/correlation${suffix}`, { signal: AbortSignal.timeout(2000) });
      assert.equal(response.status, 200);
      return response.json();
    }
    const [receivedLogs, receivedSpans] = await Promise.all([receipt(''), receipt('/traces')]);
    assert.equal(receivedLogs.accepted, 22);
    assert.equal(receivedSpans.accepted, 20);
    assert.equal(receivedLogs.requests, 1);
    assert.equal(receivedSpans.requests, 1);
    const spans = new Map(receivedSpans.spans.map(s => [`${s.trace_id}/${s.span_id}`, s]));
    const records = new Map(receivedLogs.records.map(r => [r.body.stringValue, r]));
    assert.equal(spans.size, 20);
    assert.equal(records.size, 22);
    for (const [body, sc] of expected) {
      assert.equal(sc.traceFlags & 1, 1);
      const record = records.get(body);
      assert.deepEqual([record.trace_id, record.span_id, record.flags & 0xff], [sc.traceId, sc.spanId, sc.traceFlags]);
      const span = spans.get(`${sc.traceId}/${sc.spanId}`);
      assert.ok(span, 'log must join the exact received span, not only its trace');
      assert.deepEqual(record.resource['service.name'], { stringValue: 'node-correlation' });
      assert.deepEqual(record.resource['service.name'], span.resource['service.name']);
      if (body.startsWith('child-')) {
        const parent = expected.get(body.replace('child-', 'parent-'));
        assert.equal(span.parent_span_id, parent.spanId);
        assert.equal(sc.traceId, parent.traceId);
      }
    }
    const record = records.get('unsampled');
    assert.deepEqual([record.trace_id, record.span_id, record.flags & 0xff], [unsampled.traceId, unsampled.spanId, unsampled.traceFlags]);
    assert.equal(spans.has(`${unsampled.traceId}/${unsampled.spanId}`), false);
    assert.deepEqual([records.get('outside').trace_id, records.get('outside').span_id], ['', '']);
    assert.equal(sink.length, 22);
  } finally {
    logger.close();
    await provider.shutdown();
    await Promise.all(providers.map(p => p.shutdown()));
  }
});
