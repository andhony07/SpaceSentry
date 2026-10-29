import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, TERMINAL_SCAN_STATES, cancelScan, getScanStatus, startScan } from "./api";
import type { ScanStatus } from "../types";

/**
 * Session-level scan state shared across pages.
 *
 * Polling contract: poll GET /scans/{id} until a terminal status
 * (completed/cancelled/failed) or until the consumer unmounts; stop after
 * repeated network failures so a dead backend cannot cause endless churn.
 * Analysis endpoints are intentionally NOT called before the scan reaches a
 * terminal state, and cancelled scans carry their partial flag through the
 * analysis responses.
 */

const POLL_INTERVAL_MS = 600;
const MAX_CONSECUTIVE_NETWORK_ERRORS = 3;

export interface ScanSession {
  scanId: string;
  status: ScanStatus["status"];
  snapshot: ScanStatus | null;
  lastError: string | null;
  /** True when the last error was "backend unreachable" rather than an HTTP error. */
  unreachable: boolean;
}

interface ScanManagerValue extends Omit<ScanSession, "status"> {
  status: SessionOrIdleStatus;
  beginScan: (roots: string[]) => Promise<void>;
  abortScan: () => Promise<void>;
  clearScan: () => void;
  /** True while a scan is running and analysis must not be requested yet. */
  readyForAnalysis: boolean;
  currentRoots: string[];
}

type SessionOrIdleStatus = ScanSession["status"] | "idle";

const ScanManagerContext = createContext<ScanManagerValue | null>(null);

export function ScanManagerProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<ScanSession | null>(null);
  const [roots, setRoots] = useState<string[]>([]);
  const pollTimerRef = useRef<number | null>(null);
  const pollAbortedRef = useRef(false);

  useEffect(
    () => () => {
      // Unmount: stop polling and abort any in-flight status request.
      pollAbortedRef.current = true;
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      abortControllerRef.current?.abort();
    },
    [],
  );

  const abortControllerRef = useRef<AbortController | null>(null);

  const poll = useCallback((scanId: string, attempts: number) => {
    if (pollAbortedRef.current) return;
    pollTimerRef.current = null;
    const controller = new AbortController();
    abortControllerRef.current = controller;
    getScanStatus(scanId, controller.signal)
      .then((snapshot) => {
        if (pollAbortedRef.current) return;
        setSession({
          scanId,
          status: snapshot.status,
          snapshot,
          lastError: null,
          unreachable: false,
        });
        if (TERMINAL_SCAN_STATES.has(snapshot.status)) {
          return; // stop polling on terminal state
        }
        pollTimerRef.current = window.setTimeout(() => poll(scanId, 0), POLL_INTERVAL_MS);
      })
      .catch((error) => {
        if (pollAbortedRef.current || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }
        if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
          // The scan record is gone or unreadable: stop polling and surface it.
          setSession((prev) =>
            prev && prev.scanId === scanId
              ? { ...prev, status: "failed", lastError: error.message, unreachable: false }
              : prev,
          );
          return;
        }
        // Network-level failure: retry a bounded number of times.
        const nextAttempts = attempts + 1;
        if (nextAttempts >= MAX_CONSECUTIVE_NETWORK_ERRORS) {
          setSession((prev) =>
            prev && prev.scanId === scanId
              ? { ...prev, lastError: error.message, unreachable: true }
              : prev,
          );
          return;
        }
        pollTimerRef.current = window.setTimeout(() => poll(scanId, nextAttempts), POLL_INTERVAL_MS);
      });
  }, []);

  const beginScan = useCallback(
    async (nextRoots: string[]) => {
      pollAbortedRef.current = false;
      abortControllerRef.current?.abort();
      setRoots(nextRoots);
      const created = await startScan(nextRoots);
      setSession({
        scanId: created.scan_id,
        status: "queued",
        snapshot: null,
        lastError: null,
        unreachable: false,
      });
      poll(created.scan_id, 0);
    },
    [poll],
  );

  const abortScan = useCallback(async () => {
    if (!session) return;
    // Cancel through the existing API; polling will then observe the
    // terminal cancelled status naturally.
    await cancelScan(session.scanId);
  }, [session]);

  const clearScan = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    abortControllerRef.current?.abort();
    setSession(null);
  }, []);

  const value: ScanManagerValue = {
    scanId: session?.scanId ?? "",
    status: session?.status ?? "idle",
    snapshot: session?.snapshot ?? null,
    lastError: session?.lastError ?? null,
    unreachable: session?.unreachable ?? false,
    beginScan,
    abortScan,
    clearScan,
    readyForAnalysis:
      session !== null && TERMINAL_SCAN_STATES.has(session.status) && session.status !== "failed",
    currentRoots: roots,
  };

  return <ScanManagerContext.Provider value={value}>{children}</ScanManagerContext.Provider>;
}

export function useScanManager(): ScanManagerValue {
  const value = useContext(ScanManagerContext);
  if (!value) {
    throw new Error("useScanManager must be used inside ScanManagerProvider");
  }
  return value;
}
