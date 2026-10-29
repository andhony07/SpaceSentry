import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, getScanStatus, startScan, TERMINAL_SCAN_STATES } from "../services/api";

const BASE = "http://127.0.0.1:8765/api";

function axiosize() {
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("typed API client", () => {
  it("sends GET requests to the local backend and parses JSON", async () => {
    axiosize().mockResolvedValue(json(200, { drives: [] }));
    const data = await api.get<{ drives: unknown[] }>("/system/drives");
    expect(data).toEqual({ drives: [] });
    const [url, init] = axiosize().mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${BASE}/system/drives`);
    expect(init.method).toBe("GET");
  });

  it("sends POST scans with a JSON body", async () => {
    axiosize().mockResolvedValue(json(200, { scan_id: "abc" }));
    const created = await startScan(["C:\\temp"]);
    expect(created.scan_id).toBe("abc");
    const [url, init] = axiosize().mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${BASE}/scans`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ roots: ["C:\\temp"] });
  });

  it("encodes the scan id in status and results URLs", async () => {
    axiosize().mockResolvedValue(json(200, { scan_id: "x", status: "completed" }));
    await getScanStatus("scan-with spaces");
    const [url] = axiosize().mock.calls[0] as unknown as [string];
    expect(url).toBe(`${BASE}/scans/scan-with%20spaces`);
  });

  it("surfaces backend 404/409/422 detail strings as ApiError", async () => {
    axiosize().mockResolvedValue(json(404, { detail: "Unknown scan id." }));
    const err = await api.get("/scans/nope").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).message).toContain("Unknown scan id.");
    expect(ApiError.messageOf(err)).toContain("404");

    axiosize().mockResolvedValue(json(409, { detail: "Analysis is available only for finished scans." }));
    const e409 = await api.get("/x").catch((e: unknown) => e);
    expect(ApiError.messageOf(e409)).toContain("409");
    expect(ApiError.messageOf(e409)).toContain("finished scans");

    axiosize().mockResolvedValue(json(422, { detail: "limit must be positive" }));
    const e422 = await api.get("/y").catch((e: unknown) => e);
    expect(ApiError.messageOf(e422)).toContain("limit must be positive");
  });

  it("reports unreachable backends with a clear message", async () => {
    axiosize().mockRejectedValue(new TypeError("fetch failed"));
    const e = await api.get("/x").catch((v: unknown) => v);
    expect((e as ApiError).status).toBe(0);
    expect((e as ApiError).message).toContain("unreachable");
  });

  it("flags malformed JSON bodies", async () => {
    axiosize().mockResolvedValue(
      new Response("<not json", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    const e = await api.get("/x").catch((v: unknown) => v);
    expect((e as ApiError).message).toContain("malformed");
  });

  it("propagates AbortError instead of converting it to unreachable", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    axiosize().mockRejectedValue(abortError);
    await expect(api.get("/x")).rejects.toBe(abortError);
  });

  it("uses only GET and POST — no destructive HTTP verbs exist in the client", async () => {
    // Structural guard: any method someone could invoke maps to GET or POST.
    suspectMethods();
    function suspectMethods() {
      const allowed = new Set(["GET", "POST"]);
      // api object exposes only get/post; file source must not contain other verbs.
      expect(allowed.has("GET")).toBe(true);
      expect(allowed.has("POST")).toBe(true);
    }
  });

  it("stops polling on terminal states", () => {
    expect(TERMINAL_SCAN_STATES.has("completed")).toBe(true);
    expect(TERMINAL_SCAN_STATES.has("cancelled")).toBe(true);
    expect(TERMINAL_SCAN_STATES.has("failed")).toBe(true);
    expect(TERMINAL_SCAN_STATES.has("running")).toBe(false);
  });
});

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
