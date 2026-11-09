const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { Writable } = require('node:stream');
const { context, trace, logs } = require('@opentelemetry/api');
const { AsyncLocalStorageContextManager } = require('@opentelemetry/context-async-hooks');
const { LoggerProvider, SimpleLogRecordProcessor, InMemoryLogRecordExporter } = require('@opentelemetry/sdk-logs');
const { OTLPLogExporter } = require('@opentelemetry/exporter-logs-otlp-proto');
const { OpenTelemetryTransportV3 } = require('@opentelemetry/winston-transport');
const winston = require('winston');

context.setGlobalContextManager(new AsyncLocalStorageContextManager().enable());
after(() => { context.disable(); logs.disable(); });

for (const scenario of ['healthy', 'partial', 'stall']) {
  test(`real OTLP/HTTP exporter and receiver: ${scenario}`, { timeout: 3000 }, async t => {
    const base = process.env.LOGGING_CONTRACT_RECEIVER_URL;
    if (!base) { t.skip('Use run_logging_contract.py for the owned loopback receiver'); return; }
    assert.equal(new URL(base).hostname, '127.0.0.1');
    const origin = new URL(base).origin;
    const key = new URL(base).pathname.slice(1);
    async function get(path) {
      const response = await fetch(`${origin}/${path}`, { signal: AbortSignal.timeout(1000) });
      assert.equal(response.status, 200);
      return response.json();
    }
    const memory = new InMemoryLogRecordExporter();
    const provider = new LoggerProvider({ processors: [new SimpleLogRecordProcessor({ exporter: memory })] });
    logs.disable();
    logs.setGlobalLoggerProvider(provider);
    const sink = [];
    const stream = new Writable({ write(chunk, _, done) { sink.push(chunk.toString()); done(); } });
    const logger = winston.createLogger({ transports: [
      new winston.transports.Stream({ stream }), new OpenTelemetryTransportV3(),
    ] });
    const exporter = new OTLPLogExporter({ url: `${base}/${scenario}/v1/logs`, timeoutMillis: 200 });
    try {
      const expected = scenario === 'stall' ? 1 : 3;
      const parent = trace.setSpanContext(context.active(), { traceId: '11'.repeat(16), spanId: '22'.repeat(8), traceFlags: 0 });
      context.with(parent, () => {
        for (let i = 0; i < expected; i++) logger.error(`wire-${i}`);
      });
      await provider.forceFlush();
      const started = Date.now();
      const batch = memory.getFinishedLogRecords();
      const result = await new Promise(resolve => exporter.export(batch, resolve));
      assert.equal(result.code, scenario === 'stall' ? 1 : 0, result.error?.stack);
      assert.ok(Date.now() - started < 2000);
      const receipt = await get(`evidence/${key}/${scenario}`);
      assert.equal(receipt.received, expected);
      receipt.records.forEach((record, i) => {
        assert.deepEqual(record.body, { stringValue: `wire-${i}` });
        assert.equal(record.trace_id, '11'.repeat(16));
        assert.equal(record.span_id, '22'.repeat(8));
        assert.equal(record.flags & 0xff, 0);
        assert.equal(record.severity, 17);
        const [seconds, nanoseconds] = batch[i].hrTime;
        assert.equal(BigInt(record.timestamp_unix_nano), BigInt(seconds) * 1000000000n + BigInt(nanoseconds));
      });
      if (scenario === 'stall') {
        assert.equal(receipt.accepted, 0);
        assert.equal(receipt.pending, 1);
        await get(`release-stall/${key}/${scenario}`);
        const deadline = Date.now() + 1000;
        let late;
        do {
          late = await get(`evidence/${key}/${scenario}`);
          if (!late.pending) break;
          await new Promise(resolve => setTimeout(resolve, 10));
        } while (Date.now() < deadline);
        assert.equal(late.accepted, 1);
      } else {
        assert.equal(receipt.requests, 1);
        assert.deepEqual([receipt.accepted, receipt.rejected], scenario === 'partial' ? [1, 2] : [3, 0]);
      }
      assert.equal(sink.length, expected);
      logger.info('application continued');
      assert.ok(sink.at(-1).includes('application continued'));
    } finally {
      if (scenario === 'stall') await get(`release-stall/${key}/${scenario}`);
      await exporter.shutdown();
      logger.close();
      await provider.shutdown();
    }
  });
}
