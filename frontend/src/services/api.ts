import type {
  DrivesResponse,
  LargeFilesResponse,
  DuplicatesResponse,
  FindingsResponse,
  RecommendationsResponse,
  ScanCreatedResponse,
  ScanStatus,
} from "../types";

/**
 * Typed client for the local SpaceSentry backend.
 *
 * Security posture: the ONLY allowed backend is the local FastAPI server,
 * identified by an origin allowlist below. User input is never used as a
 * server address — VITE_SPACESSENTRY_API_URL comes from build configuration
 * and is still validated against the allowlist.
 *
 * Only GET and POST exist in the backend; there is deliberately no DELETE
 * or any destructive call in this client (asserted in tests).
 */

const LOCAL_HOSTNAME = /^(localhost|127\.0\.0\.1|\[::1\]|::1)$/i;

const CONFIGURED_URL: string =
  (import.meta.env.VITE_SPACESSENTRY_API_URL as string | undefined) ??
  "http://127.0.0.1:8765/api";

function resolveBaseUrl(): string {
  const raw = CONFIGURED_URL.trim().replace(/\/+$/, "");
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("Invalid VITE_SPACESSENTRY_API_URL: not a valid URL");
  }
  if (parsed.protocol !== "http:") {
    throw new Error("SpaceSentry only supports a plain-http local backend");
  }
  if (!LOCAL_HOSTNAME.test(parsed.hostname)) {
    throw new Error("SpaceSentry only talks to the local backend");
  }
  return raw;
}

export const API_BASE_URL = resolveBaseUrl();

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** Human-readable message for any thrown value. */
  static messageOf(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 0) return error.message;
      if (error.status === 404) return `Not found (404): ${error.message}`;
      if (error.status === 409) return `Conflict (409): ${error.message}`;
      if (error.status === 422) return `Invalid request (422): ${error.message}`;
      if (error.status >= 500) return `Backend error (${error.status}): ${error.message}`;
      return `${error.status}: ${error.message}`;
    }
    if (error instanceof Error) return error.message;
    return String(error);
  }
}

interface RequestOptions {
  signal?: AbortSignal;
}

async function request<T>(path: string, init: RequestInit, options: RequestOptions): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: options.signal,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "SpaceSentry backend is unreachable. Is it running?");
  }
  if (!response.ok) {
    let detail = response.statusText;
    if (response.status === 404 && !detail) detail = "resource not found";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; fall back to statusText.
    }
    throw new ApiError(response.status, detail || `HTTP ${response.status}`);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(response.status, "Backend returned a malformed response");
  }
}

export const api = {
  get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return request<T>(path, { method: "GET" }, { signal });
  },
  post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    return request<T>(
      path,
      { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) },
      { signal },
    );
  },
};

/** Terminal scan states — polling stops on any of these. */
export const TERMINAL_SCAN_STATES = new Set(["completed", "cancelled", "failed"]);

/* ------------------------------------------------- named wrappers ------- */

export function listDrives(signal?: AbortSignal): Promise<DrivesResponse> {
  return api.get<DrivesResponse>("/system/drives", signal);
}

export function startScan(roots: string[], signal?: AbortSignal): Promise<ScanCreatedResponse> {
  return api.post<ScanCreatedResponse>("/scans", { roots }, signal);
}

export function getScanStatus(scanId: string, signal?: AbortSignal): Promise<ScanStatus> {
  return api.get<ScanStatus>(`/scans/${encodeURIComponent(scanId)}`, signal);
}

export function getScanResults(
  scanId: string,
  limit = 500,
  signal?: AbortSignal,
): Promise<{ scan_id: string; status: string; files: Array<Record<string, unknown>>; directories: Array<Record<string, unknown>>; truncated: boolean }> {
  return api.get(`/scans/${encodeURIComponent(scanId)}/results?limit=${limit}`, signal);
}

export function cancelScan(scanId: string, signal?: AbortSignal): Promise<{ scan_id: string; status: string }> {
  return api.post(`/scans/${encodeURIComponent(scanId)}/cancel`, undefined, signal);
}

export function getLargeFiles(
  scanId: string,
  options: { min_size_bytes?: number; limit?: number } = {},
  signal?: AbortSignal,
): Promise<LargeFilesResponse> {
  const params = new URLSearchParams();
  if (options.min_size_bytes !== undefined) params.set("min_size_bytes", String(options.min_size_bytes));
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  const qs = params.toString();
  return api.get<LargeFilesResponse>(`/scans/${encodeURIComponent(scanId)}/analysis/large-files${qs ? `?${qs}` : ""}`, signal);
}

export function getDuplicates(scanId: string, signal?: AbortSignal): Promise<DuplicatesResponse> {
  return api.get<DuplicatesResponse>(`/scans/${encodeURIComponent(scanId)}/analysis/duplicates`, signal);
}

export function getFindings(scanId: string, signal?: AbortSignal): Promise<FindingsResponse> {
  return api.get<FindingsResponse>(`/scans/${encodeURIComponent(scanId)}/analysis/findings`, signal);
}

export function getRecommendations(scanId: string, signal?: AbortSignal): Promise<RecommendationsResponse> {
  return api.get<RecommendationsResponse>(`/scans/${encodeURIComponent(scanId)}/analysis/recommendations`, signal);
}
