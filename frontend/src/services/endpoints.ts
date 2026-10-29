/**
 * Single source of truth for backend endpoint paths (as implemented in
 * backend/app/api/scans.py, analysis.py, system.py). Pages must import from
 * here instead of typing raw strings, so frontend/backend drift is caught in
 * one file.
 */

export function scanStatusUrl(scanId: string): string {
  // Backend route: GET /scans/{scan_id} (there is no /status suffix).
  return `/scans/${encodeURIComponent(scanId)}`;
}

export function scanResultsUrl(scanId: string, limit?: number): string {
  const q = limit != null ? `?limit=${limit}` : "";
  return `/scans/${encodeURIComponent(scanId)}/results${q}`;
}

export function scansListUrl(): string {
  return "/scans";
}

export function scanCancelUrl(scanId: string): string {
  return `/scans/${encodeURIComponent(scanId)}/cancel`;
}

export function largeFilesUrl(scanId: string, params?: { min_size_bytes?: number; limit?: number }): string {
  const qs = new URLSearchParams();
  if (params?.min_size_bytes != null) qs.set("min_size_bytes", String(params.min_size_bytes));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const q = qs.size > 0 ? `?${qs.toString()}` : "";
  return `/scans/${encodeURIComponent(scanId)}/analysis/large-files${q}`;
}

export function duplicatesUrl(scanId: string): string {
  return `/scans/${encodeURIComponent(scanId)}/analysis/duplicates`;
}

export function findingsUrl(scanId: string): string {
  return `/scans/${encodeURIComponent(scanId)}/analysis/findings`;
}

export function recommendationsUrl(scanId: string): string {
  return `/scans/${encodeURIComponent(scanId)}/analysis/recommendations`;
}

export function drivesUrl(): string {
  return "/system/drives";
}

export function healthUrl(): string {
  return "/health";
}
