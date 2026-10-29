import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpDown,
  Database,
  Eye,
  FileCode,
  FileText,
  Filter,
  Info,
  RotateCw,
  Search,
  X,
} from "lucide-react";
import { ApiError, getLargeFiles } from "../services/api";
import { useScanManager } from "../services/scanManager";
import {
  Button,
  CopyButton,
  EmptyState,
  ErrorPanel,
  LoadingPanel,
  Modal,
  PartialNotice,
  StatTile,
  TextInput,
} from "../components/ui";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableCell,
} from "../components/ui/table";
import { basename, dirname, formatBytes, formatTimestamp } from "../utils/format";
import type { LargeFileEntry, LargeFilesResponse } from "../types";

const PAGE_SIZE = 25;
const MAX_LIMIT = 1000;
const DEFAULT_MIN_BYTES = 1024 * 1024; // 1 MB

const SIZE_PRESETS = [
  { label: "1 MB", bytes: 1024 * 1024 },
  { label: "10 MB", bytes: 10 * 1024 * 1024 },
  { label: "50 MB", bytes: 50 * 1024 * 1024 },
  { label: "100 MB", bytes: 100 * 1024 * 1024 },
  { label: "500 MB", bytes: 500 * 1024 * 1024 },
  { label: "1 GB", bytes: 1024 * 1024 * 1024 },
];

type SortKey = "size" | "mtime" | "path";

export function LargeFiles() {
  const { status, scanId, readyForAnalysis } = useScanManager();

  const [minSize, setMinSize] = useState(DEFAULT_MIN_BYTES);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState<SortKey>("size");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [data, setData] = useState<LargeFilesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [inspectFile, setInspectFile] = useState<LargeFileEntry | null>(null);

  useEffect(() => {
    if (!readyForAnalysis || scanId === "") return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      getLargeFiles(scanId, { min_size_bytes: minSize, limit: MAX_LIMIT }, controller.signal)
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
    }, 300);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [scanId, minSize, readyForAnalysis, reload]);

  useEffect(() => {
    setPage(1);
  }, [query, minSize]);

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLowerCase();
    const filtered =
      needle === ""
        ? [...data.files]
        : data.files.filter((f) => f.path.toLowerCase().includes(needle));
    const dir = sortDir === "asc" ? 1 : -1;
    filtered.sort((a, b) => {
      if (sortKey === "size") return (a.size - b.size) * dir || a.path.localeCompare(b.path);
      if (sortKey === "mtime") return (a.mtime - b.mtime) * dir || a.path.localeCompare(b.path);
      return a.path.localeCompare(b.path) * dir;
    });
    return filtered;
  }, [data, query, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageRows = rows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "path" ? "asc" : "desc");
    }
    setPage(1);
  };

  const sortIndicator = (key: SortKey) => {
    if (sortKey !== key) {
      return <ArrowUpDown size={12} className="opacity-40" aria-hidden />;
    }
    return <span className="text-sentry-400 font-bold">{sortDir === "asc" ? "↑" : "↓"}</span>;
  };

  if (!readyForAnalysis) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="lf-title">
        <h1 id="lf-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Large Files
        </h1>
        <div className="mt-6">
          <EmptyState
            icon={<Eye className="text-sentry-400" size={24} />}
            title="Analysis needs a finished scan"
            description={
              status === "running" || status === "queued"
                ? "A scan is currently running. Large-file results will appear here once it completes or is cancelled."
                : "No completed scan is available yet. Open Scan Storage, choose a directory you own, and run a read-only scan first."
            }
          />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="lf-title">
        <h1 id="lf-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Large Files
        </h1>
        <ErrorPanel
          title="Could not load large-file analysis"
          message={error}
          onRetry={() => setReload((r) => r + 1)}
        />
      </section>
    );
  }

  if (loading && !data) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="lf-title">
        <div className="flex items-center justify-between">
          <h1 id="lf-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Large Files
          </h1>
        </div>
        <div className="mt-6">
          <LoadingPanel label="Analyzing large-file distribution across scanned catalog…" />
        </div>
      </section>
    );
  }

  return (
    <section className="p-6 md:p-8 space-y-6" aria-labelledby="lf-title">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 id="lf-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Large Files
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Identify disk-heavy files above customizable capacity thresholds
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
      {data && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Files Above Threshold"
            icon={<FileText size={18} className="text-sentry-400" />}
            value={data.eligible_count.toLocaleString()}
            hint={`Files matching ≥ ${formatBytes(minSize)}`}
          />
          <StatTile
            label="Combined Volume"
            icon={<Database size={18} className="text-sentry-400" />}
            value={formatBytes(data.total_eligible_bytes)}
            hint="Total verified byte size of eligible files"
          />
          <StatTile
            label="Total Files in Scan"
            icon={<FileCode size={18} className="text-sentry-400" />}
            value={data.total_files.toLocaleString()}
            hint="Cataloged files in this scan"
          />
          <StatTile
            label="Results Returned"
            icon={<Eye size={18} className="text-sentry-400" />}
            value={`${data.files.length.toLocaleString()} / ${MAX_LIMIT.toLocaleString()}`}
            hint={data.truncated ? "Server response truncated at max limit" : "All matches returned"}
          />
        </div>
      )}

      {/* Toolbar & Filters Card */}
      <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-5 shadow-sm space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          {/* Path Search */}
          <div className="relative w-full lg:max-w-xs">
            <label
              htmlFor="lf-search"
              className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-slate-400"
            >
              Filter by Filename or Directory
            </label>
            <div className="relative">
              <Search
                size={14}
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <TextInput
                id="lf-search"
                className="pl-8.5 pr-8 text-xs"
                placeholder="Search file path…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  aria-label="Clear search"
                >
                  <X size={13} aria-hidden />
                </button>
              )}
            </div>
          </div>

          {/* Threshold Input & Presets */}
          <div className="flex-1 lg:max-w-md">
            <div className="flex items-center justify-between mb-1.5">
              <label
                htmlFor="lf-min-size"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-400"
              >
                Minimum Size Threshold
              </label>
              <span className="font-mono text-xs font-semibold text-sentry-300">
                ≈ {formatBytes(minSize)}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <TextInput
                id="lf-min-size"
                type="number"
                min={0}
                className="w-40 font-mono text-xs"
                value={String(minSize)}
                onChange={(e) => {
                  const parsed = Number(e.target.value);
                  setMinSize(Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0);
                }}
              />
              {/* Presets */}
              <div className="flex flex-wrap gap-1">
                {SIZE_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => setMinSize(p.bytes)}
                    className={`rounded-md px-2 py-1 font-mono text-[11px] font-medium transition-colors ${
                      minSize === p.bytes
                        ? "bg-sentry-600 text-white shadow-xs"
                        : "bg-surface-2 text-slate-300 hover:bg-surface-3 hover:text-white border border-slate-700/60"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Table or Empty State */}
      {rows.length === 0 ? (
        <EmptyState
          icon={<Filter size={24} className="text-slate-400" />}
          title="No large files match criteria"
          description={
            query.trim() !== ""
              ? `No files match path query "${query}" with minimum threshold ${formatBytes(minSize)}.`
              : data && data.eligible_count === 0
                ? `No files at or above ${formatBytes(minSize)} were cataloged in this scan.`
                : "No large-file records are available."
          }
          action={
            (query || minSize !== DEFAULT_MIN_BYTES) ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setQuery("");
                  setMinSize(DEFAULT_MIN_BYTES);
                }}
              >
                Reset filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          {/* Responsive Table */}
          <div className="overflow-x-auto rounded-xl border border-slate-800/80 bg-surface-1 shadow-card">
            <Table className="min-w-[950px] w-full">
              <TableHeader>
                <TableRow>
                  <TableCell className="w-[30%] min-w-[280px]">
                    <button
                      type="button"
                      onClick={() => toggleSort("path")}
                      className="inline-flex items-center gap-1.5 uppercase tracking-wider text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
                    >
                      Filename {sortIndicator("path")}
                    </button>
                  </TableCell>
                  <TableCell className="w-[30%] min-w-[280px]">Directory</TableCell>
                  <TableCell className="w-28 min-w-[100px] text-right">
                    <button
                      type="button"
                      onClick={() => toggleSort("size")}
                      className="inline-flex items-center justify-end w-full gap-1.5 uppercase tracking-wider text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
                    >
                      Size {sortIndicator("size")}
                    </button>
                  </TableCell>
                  <TableCell className="w-44 min-w-[140px]">
                    <button
                      type="button"
                      onClick={() => toggleSort("mtime")}
                      className="inline-flex items-center gap-1.5 uppercase tracking-wider text-xs font-semibold text-slate-400 hover:text-slate-200 transition-colors"
                    >
                      Modified {sortIndicator("mtime")}
                    </button>
                  </TableCell>
                  <TableCell className="w-24 min-w-[70px]">Type</TableCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageRows.map((f) => {
                  const fileName = basename(f.path);
                  const dir = dirname(f.path);

                  return (
                    <TableRow key={f.path} className="group">
                      {/* Filename with copy & inspect */}
                      <TableCell className="w-[30%] min-w-[280px]">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <FileCode size={14} className="shrink-0 text-slate-400" aria-hidden />
                            <span
                              className="font-mono text-xs font-semibold text-slate-100 truncate block"
                              title={fileName}
                            >
                              {fileName}
                            </span>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <CopyButton text={f.path} label="" />
                            <button
                              type="button"
                              onClick={() => setInspectFile(f)}
                              title="Inspect file details"
                              aria-label={`Inspect ${fileName}`}
                              className="inline-flex items-center justify-center rounded-md p-1 text-slate-400 hover:bg-surface-3 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sentry-400"
                            >
                              <Info size={14} aria-hidden />
                            </button>
                          </div>
                        </div>
                      </TableCell>

                      {/* Directory */}
                      <TableCell className="w-[30%] min-w-[280px]">
                        <span
                          className="font-mono text-xs text-slate-400 block truncate"
                          title={dir}
                        >
                          {dir}
                        </span>
                      </TableCell>

                      {/* Size: Right Aligned */}
                      <TableCell className="w-28 min-w-[100px] text-right whitespace-nowrap font-mono font-medium text-slate-200">
                        {formatBytes(f.size)}
                      </TableCell>

                      {/* Modified Date */}
                      <TableCell className="w-44 min-w-[140px] whitespace-nowrap font-mono text-xs text-slate-400">
                        {formatTimestamp(f.mtime)}
                      </TableCell>

                      {/* Extension */}
                      <TableCell className="w-24 min-w-[70px]">
                        <span className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-[10px] text-slate-300 ring-1 ring-slate-700/60 uppercase">
                          {f.extension ? f.extension.replace(/^\./, "") : "none"}
                        </span>
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
              <span className="font-medium text-slate-200">{Math.min(currentPage * PAGE_SIZE, rows.length)}</span> of{" "}
              <span className="font-medium text-slate-200">{rows.length.toLocaleString()}</span> result{rows.length === 1 ? "" : "s"}
              {data && data.truncated ? " (server result truncated at limit)" : ""}
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

      {/* Inspect File Modal */}
      {inspectFile && (
        <Modal
          open={Boolean(inspectFile)}
          onClose={() => setInspectFile(null)}
          title="Large File Details"
          subtitle="Direct inspection of cataloged file metadata"
        >
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Full Windows Path
                </span>
                <CopyButton text={inspectFile.path} label="Copy Path" />
              </div>
              <div className="rounded-lg border border-slate-700/80 bg-surface-2 p-3 font-mono text-xs text-slate-100 select-all break-all leading-relaxed">
                {inspectFile.path}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Recorded Size</span>
                <p className="mt-1 font-mono text-base font-semibold text-slate-100">
                  {formatBytes(inspectFile.size)}
                  <span className="ml-1.5 text-xs text-slate-400 font-normal">
                    ({inspectFile.size.toLocaleString()} bytes)
                  </span>
                </p>
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">File Type</span>
                <p className="mt-1 font-mono text-sm font-semibold text-slate-200 uppercase">
                  {inspectFile.extension || "No extension"}
                </p>
              </div>

              <div className="col-span-2 rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Last Modified</span>
                <p className="mt-1 font-mono text-xs text-slate-200">
                  {formatTimestamp(inspectFile.mtime)}
                  <span className="ml-2 text-slate-400">
                    (Epoch: {inspectFile.mtime})
                  </span>
                </p>
              </div>
            </div>

            <div className="flex justify-end pt-4 border-t border-slate-800/80">
              <Button variant="secondary" onClick={() => setInspectFile(null)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
