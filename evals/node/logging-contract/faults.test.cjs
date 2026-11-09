const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Writable } = require('node:stream');
const { logs, diag, DiagLogLevel } = require('@opentelemetry/api');
const { LoggerProvider, SimpleLogRecordProcessor, BatchLogRecordProcessor, InMemoryLogRecordExporter } = require('@opentelemetry/sdk-logs');
const { OpenTelemetryTransportV3 } = require('@opentelemetry/winston-transport');
const winston = require('winston');

after(() => { logs.disable(); diag.disable(); });

function path(exporter, batch = false) {
  logs.disable();
  const processor = batch
    ? new BatchLogRecordProcessor({ exporter, maxQueueSize: 8, maxExportBatchSize: 8, scheduledDelayMillis: 60000, exportTimeoutMillis: 1000 })
    : new SimpleLogRecordProcessor({ exporter });
  const provider = new LoggerProvider({ processors: [processor] });
  logs.setGlobalLoggerProvider(provider);
  const sink = [];
  const stream = new Writable({ write(chunk, _, done) { sink.push(chunk.toString()); done(); } });
  const logger = winston.createLogger({ transports: [
    new winston.transports.Stream({ stream }), new OpenTelemetryTransportV3(),
  ] });
  return { logger, provider, sink };
}

function logFailure(logger, error, fields) {
  // Fixture-owned policy: fixed category and explicitly permitted fields only.
  logger.error('request failed', { 'exception.type': error.name, 'request.id': fields['request.id'] });
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('real exception is minimized before bridge and original sink', { timeout: 3000 }, async () => {
  const exporter = new InMemoryLogRecordExporter();
  const s = path(exporter);
  try {
    const canary = 'password=synthetic-private-canary';
    const error = new TypeError(canary, { cause: new Error(canary) });
    const fields = { 'request.id': 'request-1', payload: { token: canary }, 'error.kind': error.name };
    s.logger.error('unsafe control', { error, ...fields });
    await s.provider.forceFlush();
    const unsafe = exporter.getFinishedLogRecords()[0];
    assert.equal(unsafe.attributes['exception.message'], canary);
    assert.ok(unsafe.attributes['exception.stacktrace'].includes(canary));
    assert.equal(unsafe.attributes['error.kind'], 'TypeError');
    assert.ok(s.sink.join('').includes(canary));
    s.sink.length = 0;
    logFailure(s.logger, error, fields);
    await s.provider.forceFlush();
    const safe = exporter.getFinishedLogRecords()[1];
    assert.equal(safe.attributes['exception.type'], 'TypeError');
    assert.equal(safe.attributes['request.id'], 'request-1');
    assert.equal(safe.body, 'request failed');
    assert.equal(safe.attributes['exception.message'], undefined);
    assert.equal(safe.attributes['exception.stacktrace'], undefined);
    assert.equal(safe.attributes.payload, undefined);
    assert.equal(safe.attributes['error.kind'], undefined);
    assert.ok(!JSON.stringify({ body: safe.body, attributes: safe.attributes }).includes(canary));
    assert.ok(!s.sink.join('').includes(canary));
    assert.equal(s.sink.length, 1);
  } finally { s.logger.close(); await s.provider.shutdown(); }
});

test('overload bounds batches and exposes local loss while original sink continues', { timeout: 3000 }, async () => {
  const entered = deferred();
  const release = deferred();
  const bodies = [];
  const sizes = [];
  const exporter = {
    export(batch, done) {
      entered.resolve();
      release.promise.then(() => {
        sizes.push(batch.length);
        bodies.push(...batch.map(record => record.body));
        done({ code: 0 });
      });
    },
    async forceFlush() {},
    async shutdown() { release.resolve(); },
  };
  const s = path(exporter, true);
  const attempted = 48;
  try {
    for (let i = 0; i < 8; i++) s.logger.info(`record-${i}`);
    await entered.promise;
    for (let i = 8; i < attempted; i++) s.logger.info(`record-${i}`);
    assert.equal(s.sink.length, attempted);
    release.resolve();
    await s.provider.forceFlush();
    const exported = bodies.length;
    assert.ok(exported >= 8 && exported < attempted);
    assert.equal(new Set(bodies).size, exported);
    assert.ok(Math.max(...sizes) <= 8);
    const inferredLocalDrops = attempted - exported;
    assert.ok(inferredLocalDrops > 0);
  } finally { release.resolve(); s.logger.close(); await s.provider.shutdown(); }
});

test('SDK failure diagnostics are visible outside the application bridge', { timeout: 3000 }, async () => {
  let calls = 0;
  const diagnostics = [];
  const exporter = {
    export(_, done) { calls++; done({ code: 1, error: new Error('synthetic receiver unavailable') }); },
    async forceFlush() {},
    async shutdown() {},
  };
  const s = path(exporter, true);
  diag.setLogger({
    error(...args) { diagnostics.push(args); }, warn() {}, info() {}, debug() {}, verbose() {},
  }, DiagLogLevel.ERROR);
  try {
    s.logger.error('first failure');
    await s.provider.forceFlush();
    s.logger.info('application continued');
    await s.provider.forceFlush();
    assert.equal(calls, 2);
    assert.ok(diagnostics.length >= 1 && diagnostics.length <= 4);
    assert.equal(s.sink.length, 2);
    assert.ok(s.sink[1].includes('application continued'));
  } finally { diag.disable(); s.logger.close(); await s.provider.shutdown(); }
});
