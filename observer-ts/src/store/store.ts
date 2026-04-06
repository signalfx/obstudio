import type { Signal, Span, MetricDataPoint, LogRecord } from "./types.ts";

type Subscriber = (signal: Signal) => void;

export interface StoreOptions {
  sessionGap?: number; // milliseconds, default 30000
}

export class Store {
  private spans: Span[] = [];
  private metrics: MetricDataPoint[] = [];
  private logs: LogRecord[] = [];
  private lastIngest = 0;
  private sessionGap: number;

  private subscribers = new Map<number, Subscriber>();
  private nextSubId = 0;

  constructor(opts?: StoreOptions) {
    this.sessionGap = opts?.sessionGap ?? 30_000;
  }

  // --- Accessors (for query module) ---

  getSpans(): readonly Span[] {
    return this.spans;
  }

  getMetrics(): readonly MetricDataPoint[] {
    return this.metrics;
  }

  getLogs(): readonly LogRecord[] {
    return this.logs;
  }

  // --- Mutations ---

  addSpans(spans: Span[]): void {
    const reset = this.checkSessionReset();
    this.spans.push(...spans);
    this.lastIngest = Date.now();
    if (reset) {
      this.notify("traces");
      this.notify("metrics");
      this.notify("logs");
    } else {
      this.notify("traces");
    }
  }

  addMetrics(metrics: MetricDataPoint[]): void {
    const reset = this.checkSessionReset();
    this.metrics.push(...metrics);
    this.lastIngest = Date.now();
    if (reset) {
      this.notify("traces");
      this.notify("metrics");
      this.notify("logs");
    } else {
      this.notify("metrics");
    }
  }

  addLogs(logs: LogRecord[]): void {
    const reset = this.checkSessionReset();
    this.logs.push(...logs);
    this.lastIngest = Date.now();
    if (reset) {
      this.notify("traces");
      this.notify("metrics");
      this.notify("logs");
    } else {
      this.notify("logs");
    }
  }

  clear(): void {
    this.spans = [];
    this.metrics = [];
    this.logs = [];
    this.lastIngest = 0;
    this.notify("traces");
    this.notify("metrics");
    this.notify("logs");
  }

  // --- Session reset ---

  private checkSessionReset(): boolean {
    if (this.lastIngest === 0 || this.sessionGap <= 0) {
      return false;
    }
    if (Date.now() - this.lastIngest > this.sessionGap) {
      this.spans = [];
      this.metrics = [];
      this.logs = [];
      return true;
    }
    return false;
  }

  // --- Pub/sub ---

  subscribe(cb: Subscriber): number {
    const id = this.nextSubId++;
    this.subscribers.set(id, cb);
    return id;
  }

  unsubscribe(id: number): void {
    this.subscribers.delete(id);
  }

  private notify(signal: Signal): void {
    for (const cb of this.subscribers.values()) {
      try {
        cb(signal);
      } catch {
        // Ignore subscriber errors.
      }
    }
  }
}
