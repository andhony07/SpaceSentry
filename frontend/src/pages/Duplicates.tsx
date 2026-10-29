import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CopyX,
  Database,
  FileCode,
  Hash,
  Info,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { ApiError, getDuplicates } from "../services/api";
import { useScanManager } from "../services/scanManager";
import {
  Button,
  Callout,
  CopyButton,
  EmptyState,
  ErrorPanel,
  LoadingPanel,
  Modal,
  PartialNotice,
  StatTile,
} from "../components/ui";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableCell,
} from "../components/ui/table";
import { basename, dirname, formatBytes, formatHash } from "../utils/format";
import type { DuplicateGroup, DuplicatesResponse } from "../types";

const PAGE_SIZE = 10;

/** Human labels for backend exclusion reasons (duplicate_detector.py). */
const EXCLUDED_REASONS: Record<string, string> = {
  budget_exceeded: "SHA-256 hashing budget exhausted",
  changed_since_scan: "File changed since initial scan",
  changed_during_hash: "File modified while being hashed",
  unreadable: "Could not be read (permissions or locked)",
  disappeared: "File no longer exists on disk",
  reparse_point: "Reparse point or symbolic link skipped",
  swapped_during_open: "File replaced while being opened",
};

export function Duplicates() {
  const { status, scanId, readyForAnalysis } = useScanManager();

  const [data, setData] = useState<DuplicatesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [page, setPage] = useState(1);
  const [inspectGroup, setInspectGroup] = useState<DuplicateGroup | null>(null);

  useEffect(() => {
    if (!readyForAnalysis || scanId === "") return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getDuplicates(scanId, controller.signal)
      .then((response) => {
        setData(response);
        setError(null);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setData(null);
        setError(ApiError.messageOf(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [scanId, readyForAnalysis, reload]);

  const groups = data?.groups ?? [];
  const totalPages = Math.max(1, Math.ceil(groups.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageGroups = groups.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  if (!readyForAnalysis) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="dup-title">
        <h1 id="dup-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Duplicate Detection
        </h1>
        <div className="mt-6">
          <EmptyState
            icon={<CopyX className="text-sentry-400" size={24} />}
            title="Analysis needs a finished scan"
            description={
              status === "running" || status === "queued"
                ? "A scan is currently running. Duplicate-file results will appear here once it completes or is cancelled."
                : "No completed scan is available yet. Open Scan Storage, choose a directory you own, and run a read-only scan first."
            }
          />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="dup-title">
        <h1 id="dup-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Duplicate Detection
        </h1>
        <ErrorPanel
          title="Could not load duplicate analysis"
          message={error}
          onRetry={() => setReload((r) => r + 1)}
        />
      </section>
    );
  }

  if (loading && !data) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="dup-title">
        <div className="flex items-center justify-between">
          <h1 id="dup-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Duplicate Detection
          </h1>
        </div>
        <div className="mt-6">
          <LoadingPanel label="Computing SHA-256 hashes and grouping verified identical files…" />
        </div>
      </section>
    );
  }

  const excludedEntries = Object.entries(data?.excluded_counts ?? {}).filter(([, n]) => n > 0);
  const totalExcluded = excludedEntries.reduce((sum, [, n]) => sum + n, 0);

  return (
    <section className="p-6 md:p-8 space-y-6" aria-labelledby="dup-title">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 id="dup-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Duplicate Detection
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Cryptographically verified duplicate groups using SHA-256 byte hashing — filenames alone are never used as proof
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data && <PartialNotice partial={data.partial} />}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReload((r) => r + 1)}
            disabled={loading}
          >
            <RotateCw size={14} className={loading ? "animate-spin text-sentry-400" : ""} aria-hidden />
            Refresh
          </Button>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile
          label="Verified Duplicate Groups"
          icon={<CopyX size={18} className="text-sentry-400" />}
          value={(data?.duplicate_group_count ?? 0).toLocaleString()}
          hint="Groups with verified identical SHA-256 content"
        />
        <StatTile
          label="Potentially Redundant Volume"
          icon={<Database size={18} className="text-amber-400" />}
          value={formatBytes(data?.reclaimable_if_one_copy_removed ?? 0)}
          hint="Volume reclaimable if exactly one copy of each group were kept"
        />
        <StatTile
          label="Files Excluded from Hashing"
          icon={<AlertTriangle size={18} className="text-slate-400" />}
          value={totalExcluded.toLocaleString()}
          hint="Files excluded due to hash budget, locks, or modifications"
        />
      </div>

      {/* Safety Policy Callout */}
      <Callout>
        <strong>Read-Only Detection:</strong> Duplicate detection is purely diagnostic. SpaceSentry never deletes, moves, or links duplicate files. Identical content is strictly an observation, not automated authorization to remove any copy.
      </Callout>

      {/* Excluded Breakdown Alert if any */}
      {excludedEntries.length > 0 && (
        <div
          className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-4 text-xs text-amber-300"
          role="status"
        >
          <div className="font-semibold mb-1 flex items-center gap-1.5">
            <AlertTriangle size={14} /> Excluded During Content Hashing:
          </div>
          <div className="flex flex-wrap gap-2 mt-2">
            {excludedEntries.map(([reason, n]) => (
              <span
                key={reason}
                className="rounded-md bg-amber-950/40 px-2 py-1 border border-amber-500/30 font-mono text-[11px]"
              >
                {n} {EXCLUDED_REASONS[reason] ?? reason}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Main Table or Empty State */}
      {groups.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={28} className="text-emerald-400" />}
          title="No verified duplicate files detected"
          description="Every cataloged candidate file has unique content, or files could not be safely verified (see exclusions above)."
        />
      ) : (
        <>
          {/* Responsive Table */}
          <div className="overflow-x-auto rounded-xl border border-slate-800/80 bg-surface-1 shadow-card">
            <Table className="min-w-[960px] w-full">
              <TableHeader>
                <TableRow>
                  <TableCell className="w-48 min-w-[180px]">Content Hash (SHA-256)</TableCell>
                  <TableCell className="w-28 min-w-[100px] text-right">Size / File</TableCell>
                  <TableCell className="w-28 min-w-[100px] text-center">Copies</TableCell>
                  <TableCell className="w-36 min-w-[120px] text-right">Redundant If 1 Kept</TableCell>
                  <TableCell className="min-w-[340px]">Duplicate File Paths</TableCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageGroups.map((g) => {
                  const redundantBytes = g.size * (g.copy_count - 1);

                  return (
                    <TableRow key={g.hash} className="group">
                      {/* Hash Column with copy & inspect */}
                      <TableCell className="w-48 min-w-[180px]">
                        <div className="flex items-center justify-between gap-1.5">
                          <div className="flex items-center gap-1 font-mono text-xs text-sentry-300">
                            <Hash size={13} className="shrink-0 text-sentry-400" aria-hidden />
                            <span title={g.hash}>{formatHash(g.hash)}…</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <CopyButton text={g.hash} label="" />
                            <button
                              type="button"
                              onClick={() => setInspectGroup(g)}
                              title="Inspect duplicate group"
                              aria-label="Inspect group"
                              className="rounded-md p-1 text-slate-400 hover:bg-surface-3 hover:text-slate-100"
                            >
                              <Info size={14} aria-hidden />
                            </button>
                          </div>
                        </div>
                      </TableCell>

                      {/* Size per file: Right Aligned */}
                      <TableCell className="w-28 min-w-[100px] text-right whitespace-nowrap font-mono font-medium text-slate-200">
                        {formatBytes(g.size)}
                      </TableCell>

                      {/* Copies Count */}
                      <TableCell className="w-28 min-w-[100px] text-center whitespace-nowrap">
                        <span className="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold text-slate-200 ring-1 ring-slate-700/60">
                          {g.copy_count} files
                        </span>
                      </TableCell>

                      {/* Redundant Bytes: Right Aligned */}
                      <TableCell className="w-36 min-w-[120px] text-right whitespace-nowrap font-mono font-semibold text-amber-300">
                        {formatBytes(redundantBytes)}
                      </TableCell>

                      {/* Duplicate File Paths List */}
                      <TableCell className="min-w-[340px]">
                        <ul className="space-y-1.5 py-1">
                          {g.paths.map((p) => {
                            const fileName = basename(p);
                            const dir = dirname(p);

                            return (
                              <li
                                key={p}
                                className="flex items-center justify-between gap-2 rounded-lg bg-surface-2/40 px-2.5 py-1.5 border border-slate-800/60 transition-colors hover:border-slate-700/80"
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-1.5">
                                    <FileCode size={13} className="shrink-0 text-slate-400" aria-hidden />
                                    <span
                                      className="font-mono text-xs font-medium text-slate-100 truncate block"
                                      title={fileName}
                                    >
                                      {fileName}
                                    </span>
                                  </div>
                                  <div
                                    className="font-mono text-[10px] text-slate-400 truncate mt-0.2"
                                    title={p}
                                  >
                                    {dir}
                                  </div>
                                </div>
                                <CopyButton text={p} label="" className="shrink-0" />
                              </li>
                            );
                          })}
                        </ul>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          {/* Pagination Controls */}
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-400 pt-2">
            <span>
              Showing <span className="font-medium text-slate-200">{(currentPage - 1) * PAGE_SIZE + 1}</span>–
              <span className="font-medium text-slate-200">{Math.min(currentPage * PAGE_SIZE, groups.length)}</span> of{" "}
              <span className="font-medium text-slate-200">{groups.length}</span> duplicate group{groups.length === 1 ? "" : "s"}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={currentPage <= 1}
              >
                Previous
              </Button>
              <span className="font-mono text-xs px-2 text-slate-300">
                Page {currentPage} of {totalPages}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage >= totalPages}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      {/* Inspect Group Modal */}
      {inspectGroup && (
        <Modal
          open={Boolean(inspectGroup)}
          onClose={() => setInspectGroup(null)}
          title="Duplicate Group Details"
          subtitle="Cryptographically verified file set sharing identical SHA-256 digest"
        >
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Full SHA-256 Content Hash
                </span>
                <CopyButton text={inspectGroup.hash} label="Copy Hash" />
              </div>
              <div className="rounded-lg border border-slate-700/80 bg-surface-2 p-3 font-mono text-xs text-sentry-300 select-all break-all leading-relaxed">
                {inspectGroup.hash}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Size Per File</span>
                <p className="mt-1 font-mono text-base font-semibold text-slate-100">
                  {formatBytes(inspectGroup.size)}
                </p>
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Redundant Volume</span>
                <p className="mt-1 font-mono text-base font-semibold text-amber-300">
                  {formatBytes(inspectGroup.size * (inspectGroup.copy_count - 1))}
                </p>
              </div>
            </div>

            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2 block">
                Member File Paths ({inspectGroup.paths.length})
              </span>
              <ul className="space-y-2 max-h-60 overflow-y-auto pr-1">
                {inspectGroup.paths.map((p, idx) => (
                  <li
                    key={idx}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-700/80 bg-surface-2 p-2.5 font-mono text-xs text-slate-100"
                  >
                    <span className="truncate select-all">{p}</span>
                    <CopyButton text={p} label="Copy" className="shrink-0" />
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex justify-end pt-4 border-t border-slate-800/80">
              <Button variant="secondary" onClick={() => setInspectGroup(null)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
