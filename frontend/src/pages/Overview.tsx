import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  CopyX,
  Database,
  Eye,
  FileText,
  FolderSearch,
  FolderTree,
  HardDrive,
  Shield,
  Sparkles,
} from "lucide-react";
import { api, ApiError } from "../services/api";
import { drivesUrl, recommendationsUrl, largeFilesUrl, duplicatesUrl } from "../services/endpoints";
import { useScanManager } from "../services/scanManager";
import { Button, LoadingPanel, ScanStatusBadge, StatTile } from "../components/ui";
import { formatBytes } from "../utils/format";
import type { DrivesResponse } from "../types";
import type { ViewKey } from "../components/Sidebar";

export function Overview({ onNavigate }: { onNavigate: (view: ViewKey) => void }) {
  const { status, snapshot, readyForAnalysis } = useScanManager();
  const summary = snapshot?.summary ?? null;

  return (
    <section className="p-6 md:p-8 space-y-6" aria-labelledby="ov-title">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 id="ov-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Storage Intelligence Overview
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Real-time storage health, mounted drive capacities, and scan telemetry
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ScanStatusBadge status={status} />
        </div>
      </div>

      {/* Real Windows Drives Capacities */}
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
          <HardDrive size={15} className="text-sentry-400" aria-hidden /> Mounted Drive Volumes
        </h2>
        <DrivesCard />
      </div>

      {/* Primary Scan Stat Tiles */}
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
          <Activity size={15} className="text-sentry-400" aria-hidden /> Current Session Telemetry
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Scanned Files"
            icon={<FileText size={18} className="text-sentry-400" />}
            value={summary ? summary.file_count.toLocaleString() : "—"}
            hint={summary ? "Total number of files cataloged in current scan" : undefined}
          />
          <StatTile
            label="Scanned Volume"
            icon={<Database size={18} className="text-sentry-400" />}
            value={summary ? formatBytes(summary.bytes_scanned) : "—"}
            hint={summary ? "Combined byte size of cataloged files" : undefined}
          />
          <StatTile
            label="Directories Explored"
            icon={<FolderTree size={18} className="text-sentry-400" />}
            value={summary ? summary.directory_count.toLocaleString() : "—"}
            hint={summary ? "Total directories traversed during scan" : undefined}
          />
          <StatTile
            label="Scan Status"
            icon={<Activity size={18} className="text-sentry-400" />}
            value={<ScanStatusBadge status={status} />}
            hint={status === "idle" ? "No scan active" : `Current state: ${status}`}
          />
        </div>
      </div>

      {/* Analysis Deep-Dive Cards */}
      {readyForAnalysis && snapshot && (
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
            <Sparkles size={15} className="text-sentry-400" aria-hidden /> Analysis Findings
          </h2>
          <AnalysisCounts onNavigate={onNavigate} />
        </div>
      )}

      {/* Volume Visual Representation */}
      <StorageVisual />

      {/* Root Scanning Errors Alert if any */}
      {summary && summary.root_errors.length > 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-950/25 p-4 text-xs text-amber-300" role="alert">
          <span className="font-semibold">{summary.root_errors.length} root directory path(s) could not be scanned:</span>{" "}
          {summary.root_errors.join("; ")}
        </div>
      )}

      {/* Welcome / Idle State */}
      {status === "idle" && (
        <div className="rounded-xl border border-sentry-800/60 bg-sentry-950/40 p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-xl bg-sentry-800/40 text-sentry-300 ring-1 ring-sentry-500/40">
            <FolderSearch size={24} aria-hidden />
          </div>
          <h2 className="text-lg font-bold text-slate-100">Ready to initiate storage scan</h2>
          <p className="mx-auto mt-1.5 max-w-md text-sm text-slate-400 leading-relaxed">
            Specify a local directory path in <strong>Scan Storage</strong> and start a read-only scan to populate storage analytics, large files, duplicate groups, and cleanup recommendations.
          </p>
          <Button
            variant="primary"
            onClick={() => onNavigate("scan")}
            className="mt-5"
          >
            Start a Storage Scan
            <ArrowRight size={15} aria-hidden />
          </Button>
        </div>
      )}
    </section>
  );
}

/* Real Windows drive capacities from /system/drives. On error: no invented numbers. */
function DrivesCard() {
  const [drives, setDrives] = useState<DrivesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<DrivesResponse>(drivesUrl())
      .then((r) => {
        if (!cancelled) setDrives(r);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(ApiError.messageOf(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (drives === null && error === null) {
    return <LoadingPanel label="Querying Windows drive capacities…" />;
  }

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-4 text-sm text-rose-300" role="alert">
        Drive capacity query unavailable: {error}
      </div>
    );
  }

  if (!drives || drives.drives.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-4 text-sm text-slate-400">
        No fixed or removable drive volumes were reported by the backend.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {drives.drives.map((d) => {
        const used = Math.max(0, d.total_bytes - d.free_bytes);
        const pct = d.total_bytes > 0 ? used / d.total_bytes : 0;
        const pctFormatted = Math.max(0, Math.min(100, Math.round(pct * 100)));

        return (
          <div
            key={d.drive}
            className="rounded-xl border border-slate-800/80 bg-surface-1 p-4 shadow-sm transition-colors hover:border-slate-700/80"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-mono text-base font-bold text-slate-100">{d.drive}</span>
                <span className="rounded-md bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-slate-400 capitalize ring-1 ring-slate-700/60">
                  {d.drive_type || "Drive"}
                </span>
              </div>
              <span className="font-mono text-xs font-semibold text-sentry-300">
                {pctFormatted}% used
              </span>
            </div>

            {/* Capacity Progress Bar */}
            <div
              className="mt-3.5 h-2 w-full rounded-full bg-surface-2 overflow-hidden"
              role="progressbar"
              aria-valuenow={pctFormatted}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${d.drive} storage usage`}
            >
              <div
                className={`h-full transition-all duration-300 ${
                  pctFormatted > 90
                    ? "bg-rose-500"
                    : pctFormatted > 75
                      ? "bg-amber-500"
                      : "bg-sentry-500"
                }`}
                style={{ width: `${Math.max(2, pctFormatted)}%` }}
              />
            </div>

            <div className="mt-2.5 flex items-center justify-between font-mono text-[11px] text-slate-400">
              <span>{formatBytes(used)} used</span>
              <span>{formatBytes(d.free_bytes)} free / {formatBytes(d.total_bytes)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* Analysis counts only when the backend has a finished scan to analyze. */
function AnalysisCounts({ onNavigate }: { onNavigate: (view: ViewKey) => void }) {
  const { snapshot } = useScanManager();
  if (!snapshot) return null;
  const sid = snapshot.scan_id;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <InteractiveAnalysisTile
        endpoint={recommendationsUrl(sid)}
        label="Potential Cleanup Candidates"
        countKey="counts.potential_cleanup"
        hint="Policy-evaluated candidate files ready for safety review"
        icon={<Shield size={18} className="text-emerald-400" />}
        onClick={() => onNavigate("recommendations")}
      />
      <InteractiveAnalysisTile
        endpoint={largeFilesUrl(sid, { limit: 1 })}
        label="Identified Large Files"
        countKey="eligible_count"
        hint="Files exceeding threshold size criteria"
        icon={<Eye size={18} className="text-sentry-400" />}
        onClick={() => onNavigate("large")}
      />
      <InteractiveAnalysisTile
        endpoint={duplicatesUrl(sid)}
        label="Verified Duplicate Groups"
        countKey="duplicate_group_count"
        hint="Verified identical files sharing exact SHA-256 hash"
        icon={<CopyX size={18} className="text-amber-400" />}
        onClick={() => onNavigate("duplicates")}
      />
    </div>
  );
}

function InteractiveAnalysisTile({
  endpoint,
  label,
  countKey,
  hint,
  icon,
  onClick,
}: {
  endpoint: string;
  label: string;
  countKey: string;
  hint: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  const [state, setState] = useState<{ value: string; err?: boolean }>({ value: "…" });

  useEffect(() => {
    let cancelled = false;
    api
      .get<Record<string, unknown>>(endpoint)
      .then((data) => {
        if (cancelled) return;
        let cur: unknown = data;
        for (const p of countKey.split(".")) {
          if (cur && typeof cur === "object" && p in (cur as Record<string, unknown>)) {
            cur = (cur as Record<string, unknown>)[p];
          } else {
            cur = undefined;
            break;
          }
        }
        setState({ value: typeof cur === "number" ? cur.toLocaleString() : "—" });
      })
      .catch(() => {
        if (!cancelled) setState({ value: "—", err: true });
      });
    return () => {
      cancelled = true;
    };
  }, [endpoint, countKey]);

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex flex-col justify-between rounded-xl border border-slate-800/80 bg-surface-1 p-4 text-left transition-all hover:border-sentry-500/50 hover:bg-surface-2/40 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sentry-400"
    >
      <div className="flex w-full items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</span>
        <div className="transition-transform group-hover:scale-110">{icon}</div>
      </div>
      <div className="mt-2 flex items-baseline justify-between w-full">
        <span className="font-mono text-2xl font-bold text-slate-100">
          {state.value}
        </span>
        <span className="text-xs font-medium text-sentry-400 flex items-center gap-1 opacity-80 group-hover:opacity-100">
          View details <ArrowRight size={12} aria-hidden />
        </span>
      </div>
      <p className="mt-1 text-[11px] text-slate-500 truncate">{hint}</p>
    </button>
  );
}

/* Scanned-bytes bar per approved root (real summary data only). */
function StorageVisual() {
  const { snapshot } = useScanManager();
  const summary = snapshot?.summary;
  if (!summary || summary.bytes_scanned <= 0) return null;

  return (
    <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Scanned Volume Distribution
        </span>
        <span className="font-mono text-xs text-sentry-300">
          {formatBytes(summary.bytes_scanned)} total across {summary.roots.length} approved root{summary.roots.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="mt-3 h-2.5 w-full rounded-full bg-surface-2 overflow-hidden">
        <div className="h-full bg-sentry-500 rounded-full transition-all duration-500" style={{ width: "100%" }} />
      </div>

      <div className="mt-2.5 flex flex-wrap gap-2 text-[11px] text-slate-400">
        {summary.roots.map((r) => (
          <span key={r} className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-slate-300 ring-1 ring-slate-700/60">
            {r}
          </span>
        ))}
      </div>
    </div>
  );
}
