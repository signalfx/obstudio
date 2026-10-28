import { describe, expect, it } from "vitest";
import { formatDurationMs, formatUtcTimestamp } from "./format";

describe("formatDurationMs", () => {
  it("uses milliseconds under a second, seconds under a minute, then minutes", () => {
    expect(formatDurationMs(0)).toBe("0.0 ms");
    expect(formatDurationMs(123.45)).toBe("123.5 ms");
    expect(formatDurationMs(1008.3)).toBe("1.01 s");
    expect(formatDurationMs(12_345)).toBe("12.35 s");
    expect(formatDurationMs(150_000)).toBe("2.5 min");
  });

  it("switches units at the rounding boundary instead of printing 1000.0 ms", () => {
    expect(formatDurationMs(999.96)).toBe("1.00 s");
    expect(formatDurationMs(59_996)).toBe("1.0 min");
  });

  it("shows dashes for missing or non-finite values", () => {
    expect(formatDurationMs(null)).toBe("--");
    expect(formatDurationMs(undefined)).toBe("--");
    expect(formatDurationMs(Number.NaN)).toBe("--");
  });
});

describe("formatUtcTimestamp", () => {
  const now = new Date("2026-10-28T20:00:00Z");

  it("shows only the UTC time for today", () => {
    expect(formatUtcTimestamp(new Date("2026-10-28T14:03:21.123Z"), { now })).toBe("14:03:21");
    expect(formatUtcTimestamp(new Date("2026-10-28T14:03:21.123Z"), { now, millis: true })).toBe("14:03:21.123");
  });

  it("adds the UTC date for any other day", () => {
    expect(formatUtcTimestamp(new Date("2026-10-27T14:03:21.123Z"), { now })).toBe("Oct 27 14:03:21");
    expect(formatUtcTimestamp(new Date("2025-01-05T09:00:00.007Z"), { now, millis: true })).toBe("Jan 5 09:00:00.007");
  });
});
