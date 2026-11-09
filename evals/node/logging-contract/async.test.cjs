const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { context, trace, logs } = require('@opentelemetry/api');
const { AsyncLocalStorageContextManager } = require('@opentelemetry/context-async-hooks');
const { LoggerProvider, SimpleLogRecordProcessor, BatchLogRecordProcessor, InMemoryLogRecordExporter } = require('@opentelemetry/sdk-logs');
const { OpenTelemetryTransportV3 } = require('@opentelemetry/winston-transport');
const winston = require('winston');

context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
after(() => { context.disable(); logs.disable(); });
const sc = (value, flags = 1) => ({ traceId: value.toString(16).padStart(32, '0'), spanId: (value + 100).toString(16).padStart(16, '0'), traceFlags: flags });
const ctx = (value, flags = 1) => trace.setSpanContext(context.active(), sc(value, flags));
const immediate = () => new Promise(resolve => setImmediate(resolve));

function setup(batch = false) {
  logs.disable();
  const exporter = new InMemoryLogRecordExporter();
  const processor = batch ? new BatchLogRecordProcessor({ exporter, scheduledDelayMillis: 60000 }) : new SimpleLogRecordProcessor({ exporter });
  const provider = new LoggerProvider({ processors: [processor] });
  logs.setGlobalLoggerProvider(provider);
  const logger = winston.createLogger({ transports: [new OpenTelemetryTransportV3()] });
  return { exporter, provider, logger };
}

async function expect(s, expected) {
  await s.provider.forceFlush();
  const records = s.exporter.getFinishedLogRecords();
  assert.equal(records.length, Object.keys(expected).length);
  assert.equal(new Set(records.map(r => r.body)).size, records.length);
  for (const r of records) {
    const [value, flags] = expected[r.body];
    assert.deepEqual(r.spanContext, value ? sc(value, flags) : undefined, r.body);
    assert.equal(r.severityNumber, 9);
  }
}

test('parent context at scheduling survives caller detach, sampled and unsampled', { timeout: 3000 }, async () => {
  const s = setup();
  try {
    const tasks = [0, 1].map(flags => context.with(ctx(11 + flags, flags), async () => {
      await immediate(); s.logger.info(`task-${flags}`);
    }));
    s.logger.info('outside');
    await Promise.all(tasks);
    await expect(s, { 'task-0': [11, 0], 'task-1': [12, 1], outside: [0, 0] });
  } finally { await s.provider.shutdown(); }
});

test('twenty concurrent parent contexts match exact records after awaits', { timeout: 3000 }, async () => {
  const s = setup(true);
  try {
    await Promise.all(Array.from({ length: 20 }, (_, j) => {
      const i = j + 1;
      return context.with(ctx(i, i % 2), async () => {
        await immediate(); s.logger.info(`before-${i}`);
        await immediate(); s.logger.info(`after-${i}`);
      });
    }));
    await expect(s, Object.fromEntries(Array.from({ length: 20 }, (_, j) => ['before', 'after'].map(phase => [`${phase}-${j + 1}`, [j + 1, (j + 1) % 2]])).flat()));
  } finally { await s.provider.shutdown(); }
});

test('callback registration requires binding when emitted outside caller context', { timeout: 3000 }, async () => {
  const s = setup();
  try {
    const emitter = new EventEmitter();
    context.with(ctx(31), () => {
      emitter.on('raw', () => s.logger.info('raw-callback'));
      emitter.on('bound', context.bind(context.active(), () => s.logger.info('bound-callback')));
    });
    await immediate();
    emitter.emit('raw'); emitter.emit('bound'); s.logger.info('outside-after-bound');
    await expect(s, { 'raw-callback': [0, 0], 'bound-callback': [31, 1], 'outside-after-bound': [0, 0] });
  } finally { await s.provider.shutdown(); }
});

test('error and cooperative abort restore context', { timeout: 3000 }, async () => {
  const s = setup();
  try {
    const controller = new AbortController();
    const work = context.with(ctx(41), async () => {
      try {
        await new Promise((_, reject) => controller.signal.addEventListener('abort', () => reject(new Error('synthetic abort')), { once: true }));
      } finally { s.logger.info('abort-cleanup'); }
    });
    const rejected = assert.rejects(work, /synthetic abort/);
    controller.abort();
    await rejected;
    context.with(ctx(42), () => {
      assert.throws(() => context.with(ctx(43), () => { throw new Error('synthetic failure'); }), /synthetic failure/);
      s.logger.info('error-restored');
    });
    s.logger.info('outside-after-error-abort');
    await expect(s, { 'abort-cleanup': [41, 1], 'error-restored': [42, 1], 'outside-after-error-abort': [0, 0] });
  } finally { await s.provider.shutdown(); }
});

test('batch export keeps emit-time context after caller detach', { timeout: 3000 }, async () => {
  const s = setup(true);
  try {
    context.with(ctx(51, 0), () => s.logger.info('queued'));
    await context.with(ctx(99), () => s.provider.forceFlush());
    await expect(s, { queued: [51, 0] });
  } finally { await s.provider.shutdown(); }
});
