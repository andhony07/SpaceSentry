import { useState } from "react";
import {
  CopyX,
  Download,
  Eye,
  FileSpreadsheet,
  FileText,
  HardDrive,
  Loader2,
  ScrollText,
} from "lucide-react";
import { useScanManager } from "../services/scanManager";
import { api } from "../services/api";
import { toCsv, type CsvColumnSpec, type CsvScalar } from "../utils/csv";
import { Button, CopyButton, EmptyState, PartialNotice } from "../components/ui";
import type { DuplicateGroup } from "../types";

export function Reports() {
  const { status, scanId, readyForAnalysis, snapshot } = useScanManager();

  const [which, setWhich] = useState<"scan" | "large" | "duplicates">("scan");
  const [csv, setCsv] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!readyForAnalysis) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="rp-title">
        <h1 id="rp-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Storage Reports
        </h1>
        <div className="mt-6">
          <EmptyState
            icon={<ScrollText className="text-sentry-400" size={24} />}
            title="Analysis needs a finished scan"
            description={
              status === "running" || status === "queued"
                ? "A scan is currently running. Report exports will become available once it completes or is cancelled."
                : "No completed scan is available yet. Open Scan Storage, choose a directory you own, and run a read-only scan first."
            }
          />
        </div>
      </section>
    );
  }

  if (!snapshot) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="rp-title">
        <h1 id="rp-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Storage Reports
        </h1>
        <div className="mt-6 rounded-xl border border-slate-800/80 bg-surface-1 p-8 text-center text-slate-400">
          Loading scan session data…
        </div>
      </section>
    );
  }

  const partial = snapshot.status === "cancelled";

  async function generateReport() {
    setGenerating(true);
    setError(null);
    try {
      if (which === "scan") {
        const rows = buildScanRows(snapshot);
        setCsv(toCsv(SCAN_COLUMNS, rows));
      } else if (which === "large") {
        const r = await api.get<{
          files: Array<Record<string, unknown>>;
          total_files: number;
          eligible_count: number;
          total_eligible_bytes: number;
          truncated: boolean;
        }>(`/scans/${encodeURIComponent(scanId)}/analysis/large-files?limit=2000`);
        const rows = (
          r.files as Array<{ path: string; size: number; mtime: number; extension: string }>
        ).map((f) => ({ ...f }));
        setCsv(toCsv(LARGE_COLUMNS, rows));
      } else {
        const r = await api.get<{ groups: DuplicateGroup[] }>(
          `/scans/${encodeURIComponent(scanId)}/analysis/duplicates`,
        );
        const rows = (r.groups as DuplicateGroup[]).map((g) => ({
          hash: g.hash,
          size: g.size,
          copy_count: g.copy_count,
          redundant_if_one_kept: g.size * (g.copy_count - 1),
          paths: g.paths.join(" | "),
        }));
        setCsv(toCsv(DUPLICATE_COLUMNS, rows));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : `Report generation failed: ${String(e)}`);
    } finally {
      setGenerating(false);
    }
  }

  const REPORT_TYPES = [
    {
      id: "scan" as const,
      label: "Scan Summary",
      icon: HardDrive,
      description:
        "Exports session metadata, recorded file count, recorded byte volume, directory count, skipped reasons breakdown, and root errors.",
    },
    {
      id: "large" as const,
      label: "Large Files",
      icon: Eye,
      description:
        "Exports every cataloged file at or above the threshold with full Windows path, exact size in bytes, file extension, and modification epoch.",
    },
    {
      id: "duplicates" as const,
      label: "Duplicate Groups",
      icon: CopyX,
      description:
        "Exports SHA-256 verified duplicate groups, individual file sizes, copy counts, calculated redundant bytes, and member file paths.",
    },
  ];

  const currentType = REPORT_TYPES.find((t) => t.id === which) ?? REPORT_TYPES[0];

  return (
    <section className="p-6 md:p-8 space-y-6" aria-labelledby="rp-title">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 id="rp-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Storage Reports
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Export real scan and analysis telemetry as RFC 4180-compliant CSV files. No fields are fabricated.
          </p>
        </div>
        {partial && <PartialNotice partial={true} />}
      </div>

      {/* Report Selection Tabs */}
      <div className="flex flex-wrap gap-2 rounded-xl border border-slate-800/80 bg-surface-1 p-2 shadow-sm">
        {REPORT_TYPES.map((t) => {
          const active = which === t.id;
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                setWhich(t.id);
                setCsv(null);
                setError(null);
              }}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all ${
                active
                  ? "bg-sentry-600 text-white shadow-sm ring-1 ring-sentry-400"
                  : "bg-surface-2/60 text-slate-300 hover:bg-surface-3 hover:text-white border border-slate-700/60"
              }`}
            >
              <Icon size={14} className={active ? "text-white" : "text-sentry-400"} aria-hidden />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* Description & Export Toolbar */}
      <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-6 shadow-sm space-y-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-200">
            {currentType.label} Export Specification
          </h2>
          <p className="mt-1 text-xs text-slate-400 leading-relaxed max-w-2xl">
            {currentType.description}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Button
            variant="primary"
            onClick={generateReport}
            disabled={generating || !scanId}
          >
            {generating ? (
              <>
                <Loader2 size={16} className="animate-spin" aria-hidden />
                Compiling CSV Data…
              </>
            ) : (
              <>
                <FileSpreadsheet size={16} aria-hidden />
                Generate CSV Report
              </>
            )}
          </Button>

          {csv && (
            <Button
              variant="secondary"
              onClick={() => downloadCsv(which, csv)}
            >
              <Download size={15} aria-hidden />
              Download {which === "scan" ? "scan-summary.csv" : which === "large" ? "large-files.csv" : "duplicates.csv"}
            </Button>
          )}
        </div>

        {error && (
          <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-950/20 p-3 text-xs text-rose-300">
            {error}
          </div>
        )}
      </div>

      {/* CSV Preview Box */}
      {csv && (
        <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText size={15} className="text-sentry-400" />
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-300">
                Generated CSV Preview (First 12 Lines)
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-slate-400">
                {csv.split("\r\n").filter(Boolean).length} total records
              </span>
              <CopyButton text={csv} label="Copy All" />
            </div>
          </div>

          <pre className="rounded-lg border border-slate-700/80 bg-surface-2 p-4 font-mono text-xs text-slate-200 whitespace-pre-wrap overflow-x-auto leading-relaxed select-all">
            {csv.split("\r\n").slice(0, 12).join("\r\n")}
          </pre>

          {csv.split("\r\n").length > 12 && (
            <p className="text-[11px] text-slate-400">
              … plus {csv.split("\r\n").length - 12} additional rows in the downloadable export.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

type ScanRow = {
  field: string;
  value: CsvScalar;
};

const SCAN_COLUMNS: CsvColumnSpec<ScanRow>[] = [
  { key: "field", label: "Field", value: (r) => r.field },
  { key: "value", label: "Value", value: (r) => r.value },
];

function buildScanRows(snapshot: {
  scan_id: string;
  status: string;
  progress: Record<string, unknown>;
  summary: {
    roots: string[];
    file_count: number;
    bytes_scanned: number;
    directory_count: number;
    skipped: { counts: Record<string, number>; samples: Record<string, string[]> };
    root_errors: string[];
    cancelled: boolean;
    capped_files: boolean;
  } | null;
} | null): ScanRow[] {
  if (!snapshot) return [];
  const s = snapshot.summary ?? null;
  const rows: ScanRow[] = [
    { field: "scan_id", value: snapshot.scan_id },
    { field: "status", value: snapshot.status },
    { field: "roots", value: (s ?? {}).roots?.join?.(" | ") ?? "" },
    { field: "files_recorded", value: (s ?? {}).file_count ?? 0 },
    { field: "bytes_recorded", value: (s ?? {}).bytes_scanned ?? 0 },
    { field: "directories_recorded", value: (s ?? {}).directory_count ?? 0 },
    {
      field: "files_skipped",
      value: (() => {
        const c = (s ?? {}).skipped?.counts;
        return c ? Object.values(c).reduce((a: number, b: number) => a + b, 0) : 0;
      })(),
    },
    { field: "skipped_permission_denied", value: (s ?? {}).skipped?.counts?.["permission_denied"] ?? 0 },
    { field: "skipped_missing", value: (s ?? {}).skipped?.counts?.["missing"] ?? 0 },
    { field: "skipped_reparse_point", value: (s ?? {}).skipped?.counts?.["reparse_point"] ?? 0 },
    { field: "skipped_cycle_detected", value: (s ?? {}).skipped?.counts?.["cycle_detected"] ?? 0 },
    { field: "skipped_depth_limit", value: (s ?? {}).skipped?.counts?.["depth_limit"] ?? 0 },
    { field: "skipped_stat_error", value: (s ?? {}).skipped?.counts?.["stat_error"] ?? 0 },
    { field: "skipped_os_error", value: (s ?? {}).skipped?.counts?.["os_error"] ?? 0 },
    { field: "skipped_special", value: (s ?? {}).skipped?.counts?.["special"] ?? 0 },
    { field: "skipped_file_cap", value: (s ?? {}).skipped?.counts?.["file_cap"] ?? 0 },
    { field: "cancelled", value: (s ?? {}).cancelled },
    { field: "capped_files", value: (s ?? {}).capped_files },
    { field: "root_errors", value: (s ?? {}).root_errors?.join?.(" | ") ?? "" },
  ];
  return rows;
}

const LARGE_COLUMNS: CsvColumnSpec<{ path: string; size: number; mtime: number; extension: string }>[] = [
  { key: "path", label: "Path", value: (r) => r.path },
  { key: "size_bytes", label: "Size (bytes)", value: (r) => r.size },
  { key: "extension", label: "Extension", value: (r) => r.extension },
  { key: "mtime", label: "Modified (epoch seconds)", value: (r) => r.mtime },
];

const DUPLICATE_COLUMNS: CsvColumnSpec<{
  hash: string;
  size: number;
  copy_count: number;
  redundant_if_one_kept: number;
  paths: string;
}>[] = [
  { key: "content_hash", label: "Content hash (SHA-256)", value: (r) => r.hash },
  { key: "file_size_bytes", label: "File size (bytes)", value: (r) => r.size },
  { key: "copy_count", label: "Copies in group", value: (r) => r.copy_count },
  {
    key: "redundant_if_one_kept_bytes",
    label: "Redundant bytes if one copy kept",
    value: (r) => r.redundant_if_one_kept,
  },
  { key: "member_paths", label: "Member paths", value: (r) => r.paths },
];

function downloadCsv(which: string, text: string) {
  const name =
    which === "scan"
      ? "spacesentry-scan-summary.csv"
      : which === "large"
        ? "spacesentry-large-files.csv"
        : "spacesentry-duplicate-groups.csv";
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
