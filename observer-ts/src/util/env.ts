export function envOr(key: string, fallback: string): string {
  return process.env[key] || fallback;
}
