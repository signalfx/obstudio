const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Formats a duration as `123.4 ms`, `1.01 s`, or `2.5 min`. */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "--";
  // Compare against the rounding boundary so 999.96 ms reads `1.00 s`, not `1000.0 ms`.
  if (ms < 999.95) return `${ms.toFixed(1)} ms`;
  if (ms < 59_995) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

/**
 * Formats a time in UTC, matching the rest of the Explorer, and adds the date
 * (`Oct 27 14:03:21`) only when it isn't the current UTC day.
 */
export function formatUtcTimestamp(date: Date, { millis = false, now = new Date() }: { millis?: boolean; now?: Date } = {}): string {
  const iso = date.toISOString();
  const time = iso.slice(11, millis ? 23 : 19);
  if (iso.slice(0, 10) === now.toISOString().slice(0, 10)) return time;
  return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()} ${time}`;
}
