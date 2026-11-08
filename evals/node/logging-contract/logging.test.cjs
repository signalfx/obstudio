const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Writable } = require('node:stream');
const { context, trace, logs, diag, DiagLogLevel } = require('@opentelemetry/api');
const { AsyncLocalStorageContextManager } = require('@opentelemetry/context-async-hooks');
const { LoggerProvider, SimpleLogRecordProcessor, BatchLogRecordProcessor, InMemoryLogRecordExporter } = require('@opentelemetry/sdk-logs');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { OpenTelemetryTransportV3 } = require('@opentelemetry/winston-transport');
const winston = require('winston');

context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
after(() => { context.disable(); logs.disable(); diag.disable(); });

function setup(exporter = new InMemoryLogRecordExporter(), failure = false) {
  logs.disable();
  const processor = failure
    ? new BatchLogRecordProcessor({ exporter, maxQueueSize: 8, maxExportBatchSize: 8, exportTimeoutMillis: 100 })
    : new SimpleLogRecordProcessor({ exporter });
  const provider = new LoggerProvider({
    resource: resourceFromAttributes({ 'service.name': 'node-logging-contract' }),
    logRecordLimits: { attributeCountLimit: 8, attributeValueLengthLimit: 32 },
    processors: [processor],
  });
  logs.setGlobalLoggerProvider(provider);
  const sink = [];
  const stream = new Writable({ write(chunk, _, done) { sink.push(chunk.toString()); done(); } });
  const logger = winston.createLogger({
    transports: [new winston.transports.Stream({ stream }), new OpenTelemetryTransportV3()],
  });
  return { provider, exporter, logger, sink };
}

const spanContext = flags => ({ traceId: '1'.repeat(32), spanId: '2'.repeat(16), traceFlags: flags });

test('official Winston mapping, original sink and precise SDK event time', async () => {
  const s = setup();
  s.logger.error('failed');
  const at = [1730000000, 1];
  s.provider.getLogger('historical').emit({ body: 'historical', timestamp: at });
  await s.provider.forceFlush();
  const [r, historical] = s.exporter.getFinishedLogRecords();
  assert.equal(r.severityNumber, 17);
  assert.equal(r.severityText, 'error');
  assert.equal(r.resource.attributes['service.name'], 'node-logging-contract');
  assert.deepEqual(historical.hrTime, at);
  assert.ok(historical.hrTimeObserved[0] > at[0]);
  assert.equal(s.sink.filter(x => x.includes('failed')).length, 1);
  await s.provider.shutdown();
});

test('sampled, unsampled and outside context', async () => {
  const s = setup();
  for (const flags of [0, 1]) {
    context.with(trace.setSpanContext(context.active(), spanContext(flags)), () => s.logger.error('inside'));
  }
  s.logger.info('outside');
  await s.provider.forceFlush();
  const records = s.exporter.getFinishedLogRecords();
  assert.equal(records.length, 3);
  assert.deepEqual(records[0].spanContext, spanContext(0));
  assert.deepEqual(records[1].spanContext, spanContext(1));
  assert.equal(records[2].spanContext, undefined);
  await s.provider.shutdown();
});

test('concurrent async context remains isolated', async () => {
  const s = setup();
  await Promise.all(['3', '4'].map(id => context.with(
    trace.setSpanContext(context.active(), { traceId: id.repeat(32), spanId: id.repeat(16), traceFlags: 1 }),
    async () => { await new Promise(resolve => setImmediate(resolve)); s.logger.info(id); },
  )));
  await s.provider.forceFlush();
  const pairs = s.exporter.getFinishedLogRecords().map(r => [r.body, r.spanContext.traceId]);
  assert.deepEqual(pairs.sort(), [['3', '3'.repeat(32)], ['4', '4'.repeat(32)]]);
  await s.provider.shutdown();
});

test('log attribute limits and explicit exception privacy policy', async () => {
  const s = setup();
  s.logger.error('request failed', { 'exception.type': 'ValueError' });
  s.provider.getLogger('limits').emit({ body: 'x'.repeat(400), attributes: Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`k${i}`, 'v'.repeat(100)])) });
  await s.provider.forceFlush();
  const [safe, limited] = s.exporter.getFinishedLogRecords();
  assert.equal(safe.attributes['exception.type'], 'ValueError');
  assert.equal(safe.attributes['exception.message'], undefined);
  assert.equal(safe.attributes['exception.stacktrace'], undefined);
  assert.equal(Object.keys(limited.attributes).length, 8);
  assert.ok(Object.values(limited.attributes).every(v => v.length === 32));
  assert.equal(limited.droppedAttributesCount, 12);
  assert.equal(limited.body.length, 400);
  await s.provider.shutdown();
});

test('failed exporter leaves original sink and application usable without recursion', async () => {
  let calls = 0;
  let diagnostics = 0;
  diag.setLogger({ error() { diagnostics++; }, warn() {}, info() {}, debug() {}, verbose() {} }, DiagLogLevel.ERROR);
  const exporter = { export(_, done) { calls++; done({ code: 1, error: new Error('synthetic receiver unavailable') }); }, shutdown: async () => {} };
  const s = setup(exporter, true);
  const started = Date.now();
  s.logger.error('receiver unavailable');
  await s.provider.forceFlush({ timeoutMillis: 1000 });
  await s.provider.shutdown();
  assert.ok(Date.now() - started < 3000);
  assert.equal(calls, 1);
  assert.ok(diagnostics <= 2);
  assert.equal(s.sink.filter(x => x.includes('receiver unavailable')).length, 1);
});

test('explicit bridge opt-out preserves original sink', async () => {
  const s = setup();
  s.logger.transports.filter(t => t instanceof OpenTelemetryTransportV3).forEach(t => s.logger.remove(t));
  s.logger.error('disabled');
  await s.provider.forceFlush();
  assert.equal(s.exporter.getFinishedLogRecords().length, 0);
  assert.equal(s.sink.filter(x => x.includes('disabled')).length, 1);
  await s.provider.shutdown();
});
