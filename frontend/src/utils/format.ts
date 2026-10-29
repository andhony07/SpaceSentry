/** Formatting helpers for real backend numbers — no estimates, no fakes. */

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) {
    return "—";
  }
  if (bytes === 0) return "0 B";
  const negative = bytes < 0;
  const magnitude = Math.abs(bytes);
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = magnitude;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = value >= 100 || unitIndex === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${negative ? "-" : ""}${value.toFixed(digits)} ${units[unitIndex]}`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString();
}

export function formatTimestamp(epochSeconds: number | null | undefined): string {
  if (epochSeconds === null || epochSeconds === undefined || epochSeconds <= 0) return "—";
  return new Date(epochSeconds * 1000).toLocaleString();
}

/** Shorter alias used by table cells. */
export const formatTime = formatTimestamp;

/** First 16 hex characters of a SHA-256 digest, for compact group labels. */
export function formatHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  return hash.length > 16 ? hash.slice(0, 16) : hash;
}

export function formatRelativeTime(epochSeconds: number | null | undefined, now = Date.now() / 1000): string {
  if (epochSeconds === null || epochSeconds === undefined || epochSeconds <= 0) return "—";
  const diff = now - epochSeconds;
  if (diff < 0) return new Date(epochSeconds * 1000).toLocaleString();
  if (diff < 5) return "just now";
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} hr ago`;
  return `${Math.round(diff / 86400)} days ago`;
}

export function basename(path: string): string {
  // Windows-aware split that also tolerates forward slashes.
  const segments = path.split(/[\\/]/);
  return segments[segments.length - 1] ?? path;
}

export function dirname(path: string): string {
  const withoutBaseline = path.split(/[\\/]/);
  withoutBaseline.pop();
  const joined = withoutBaseline.join("\\");
  return joined === "" ? path : joined;
}

/** Percentage as a 0–100 number clamped to two decimals; pure math only. */
export function percentOf(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.min(100, Math.max(0, (part / whole) * 100));
}
