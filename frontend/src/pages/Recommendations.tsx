import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  FileCode,
  Filter,
  Info,
  RotateCw,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { ApiError, getRecommendations } from "../services/api";
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
  TextInput,
} from "../components/ui";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableCell,
} from "../components/ui/table";
import { basename, dirname, formatBytes } from "../utils/format";
import type { EvaluationEntry, RecommendationsResponse } from "../types";

const PAGE_SIZE = 20;

type Classification = "potential_cleanup" | "review_required" | "protected";

const CLASSIFICATIONS: Classification[] = [
  "potential_cleanup",
  "review_required",
  "protected",
];

const CLASS_CONFIG: Record<
  Classification,
  {
    label: string;
    textClass: string;
    badgeClass: string;
    icon: typeof Shield;
  }
> = {
  potential_cleanup: {
    label: "Potential cleanup",
    textClass: "text-emerald-400",
    badgeClass: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
    icon: Sparkles,
  },
  review_required: {
    label: "Review required",
    textClass: "text-amber-400",
    badgeClass: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
    icon: AlertTriangle,
  },
  protected: {
    label: "Protected",
    textClass: "text-rose-400",
    badgeClass: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
    icon: ShieldAlert,
  },
};

function isClassification(value: string): value is Classification {
  return value === "potential_cleanup" || value === "review_required" || value === "protected";
}

export function Recommendations() {
  const { status, scanId, readyForAnalysis } = useScanManager();

  const [data, setData] = useState<RecommendationsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<Classification | "all">("all");
  const [query, setQuery] = useState("");
  const [inspectCandidate, setInspectCandidate] = useState<EvaluationEntry | null>(null);

  useEffect(() => {
    if (!readyForAnalysis || scanId === "") return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getRecommendations(scanId, controller.signal)
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

  useEffect(() => {
    setPage(1);
  }, [filter, query]);

  const evaluations = data?.evaluations ?? [];
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return evaluations.filter((e) => {
      if (filter !== "all" && e.classification !== filter) return false;
      if (needle !== "" && !e.path.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [evaluations, filter, query]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageRows = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  if (!readyForAnalysis) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="rec-title">
        <h1 id="rec-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Cleanup Recommendations
        </h1>
        <div className="mt-6">
          <EmptyState
            icon={<Shield className="text-sentry-400" size={24} />}
            title="Analysis needs a finished scan"
            description={
              status === "running" || status === "queued"
                ? "A scan is currently running. Cleanup recommendations will appear here automatically once it completes or is cancelled."
                : "No completed scan is available yet. Open Scan Storage, choose a directory you own, and run a read-only scan first."
            }
          />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="rec-title">
        <h1 id="rec-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Cleanup Recommendations
        </h1>
        <ErrorPanel
          title="Could not load cleanup recommendations"
          message={error}
          onRetry={() => setReload((r) => r + 1)}
        />
      </section>
    );
  }

  if (loading && !data) {
    return (
      <section className="p-6 md:p-8" aria-labelledby="rec-title">
        <div className="flex items-center justify-between">
          <h1 id="rec-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Cleanup Recommendations
          </h1>
        </div>
        <div className="mt-6">
          <LoadingPanel label="Classifying findings against the cleanup policy…" />
        </div>
      </section>
    );
  }

  return (
    <section className="p-6 md:p-8 space-y-6" aria-labelledby="rec-title">
      {/* Page Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 id="rec-title" className="text-2xl font-bold tracking-tight text-slate-100">
            Cleanup Recommendations
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Intelligent candidate evaluation against safe cleanup policies and protected system rules
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

      {/* Summary Metric Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {CLASSIFICATIONS.map((cls) => {
          const cfg = CLASS_CONFIG[cls];
          const count = data?.counts?.[cls] ?? 0;
          const bytes = data?.bytes?.[cls] ?? 0;
          const Icon = cfg.icon;
          return (
            <StatTile
              key={cls}
              label={cfg.label}
              icon={<Icon size={18} className={cfg.textClass} />}
              value={
                <span className={cfg.textClass}>
                  {count.toLocaleString()}
                </span>
              }
              hint={`Combined volume: ${formatBytes(bytes)}`}
            />
          );
        })}
      </div>

      {/* Safety Policy Callout */}
      <Callout>
        <strong>Safety Guarantee:</strong> A classification is an objective explanation, never permission to delete. SpaceSentry never removes files automatically — <strong className="text-slate-200">protected</strong> candidates are permanently locked and ineligible for cleanup, and all other candidates require explicit review.
      </Callout>

      {/* Filters & Search Toolbar */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between rounded-xl border border-slate-800/80 bg-surface-1 p-4 shadow-sm">
        {/* Classification Filter Buttons */}
        <div role="group" aria-label="Filter by classification" className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setFilter("all")}
            className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
              filter === "all"
                ? "bg-sentry-600 text-white shadow-sm ring-1 ring-sentry-400"
                : "bg-surface-2 text-slate-300 hover:bg-surface-3 hover:text-slate-100 border border-slate-700/60"
            }`}
          >
            <span>All</span>
            <span className="rounded-full bg-slate-900/60 px-1.5 py-0.2 text-[10px] text-slate-300">
              {evaluations.length}
            </span>
          </button>
          {CLASSIFICATIONS.map((cls) => {
            const cfg = CLASS_CONFIG[cls];
            const active = filter === cls;
            const count = data?.counts?.[cls] ?? 0;
            return (
              <button
                key={cls}
                type="button"
                onClick={() => setFilter(cls)}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                  active
                    ? "bg-sentry-600 text-white shadow-sm ring-1 ring-sentry-400"
                    : "bg-surface-2 text-slate-300 hover:bg-surface-3 hover:text-slate-100 border border-slate-700/60"
                }`}
              >
                <span>{cfg.label}</span>
                <span className="rounded-full bg-slate-900/60 px-1.5 py-0.2 text-[10px] text-slate-300">
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Search Field */}
        <div className="relative w-full lg:w-72">
          <Search
            size={14}
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <TextInput
            id="rec-search"
            className="pl-8.5 pr-8 text-xs"
            placeholder="Filter candidates by path…"
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

      {/* Main Table or Empty State */}
      {evaluations.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={24} className="text-emerald-400" />}
          title="No cleanup candidates found"
          description="The cleanup policy produced no candidates for this scan — no files matched a cleanup rule, which is a healthy result."
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Filter size={24} className="text-slate-400" />}
          title="No matching candidates"
          description={
            query
              ? `No candidates match the path query "${query}" with filter "${filter === "all" ? "All" : CLASS_CONFIG[filter].label}".`
              : `No candidates match the "${filter === "all" ? "All" : CLASS_CONFIG[filter].label}" filter.`
          }
          action={
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setFilter("all");
                setQuery("");
              }}
            >
              Reset filters
            </Button>
          }
        />
      ) : (
        <>
          {/* Responsive Table with Sensible Minimum Column Widths & Safe Truncation */}
          <div className="overflow-x-auto rounded-xl border border-slate-800/80 bg-surface-1 shadow-card">
            <Table className="min-w-[980px] w-full">
              <TableHeader>
                <TableRow>
                  <TableCell className="w-[32%] min-w-[320px]">Candidate Path</TableCell>
                  <TableCell className="w-28 min-w-[100px] text-right">Size</TableCell>
                  <TableCell className="w-40 min-w-[140px]">Classification</TableCell>
                  <TableCell className="w-56 min-w-[190px]">Category &amp; Reason</TableCell>
                  <TableCell className="min-w-[240px]">Warnings</TableCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageRows.map((e) => {
                  const cls: Classification = isClassification(e.classification)
                    ? e.classification
                    : "review_required";
                  const cfg = CLASS_CONFIG[cls];
                  const fileName = basename(e.path);
                  const dir = dirname(e.path);

                  return (
                    <TableRow key={e.path} className="group">
                      {/* Candidate Path Column: safe truncation + inspect + copy */}
                      <TableCell className="w-[32%] min-w-[320px]">
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <FileCode size={14} className="shrink-0 text-slate-400" aria-hidden />
                              <span
                                className="font-mono text-xs font-semibold text-slate-100 truncate block"
                                title={fileName}
                              >
                                {fileName}
                              </span>
                            </div>
                            <div
                              className="font-mono text-[11px] text-slate-400 truncate mt-0.5"
                              title={e.path}
                            >
                              {dir}
                            </div>
                          </div>

                          {/* Action helper buttons */}
                          <div className="flex items-center gap-1 shrink-0">
                            <CopyButton text={e.path} label="" />
                            <button
                              type="button"
                              onClick={() => setInspectCandidate(e)}
                              title="Inspect full candidate details"
                              aria-label={`Inspect ${fileName}`}
                              className="inline-flex items-center justify-center rounded-md p-1 text-slate-400 hover:bg-surface-3 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sentry-400"
                            >
                              <Info size={14} aria-hidden />
                            </button>
                          </div>
                        </div>
                      </TableCell>

                      {/* Size Column: Right Aligned */}
                      <TableCell className="w-28 min-w-[100px] text-right whitespace-nowrap font-mono font-medium text-slate-200">
                        {formatBytes(e.size)}
                      </TableCell>

                      {/* Classification Badge Column */}
                      <TableCell className="w-40 min-w-[140px]">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium capitalize ring-1 ring-inset ${cfg.badgeClass}`}
                          title={e.eligibility_detail}
                        >
                          {cfg.label}
                        </span>
                        {!e.eligible && cls !== "protected" && (
                          <span className="mt-1 block text-[10px] text-slate-500 font-medium">
                            not eligible for cleanup
                          </span>
                        )}
                      </TableCell>

                      {/* Category & Reason Column: Clear Hierarchy */}
                      <TableCell className="w-56 min-w-[190px]">
                        <span className="block text-xs font-semibold text-slate-200">
                          {e.category}
                        </span>
                        <span className="block text-xs text-slate-400 mt-0.5 leading-relaxed">
                          {e.reason}
                        </span>
                      </TableCell>

                      {/* Warnings Column: Normal word wrapping & neutral body text */}
                      <TableCell className="min-w-[240px] whitespace-normal">
                        {e.warnings.length > 0 ? (
                          <div className="flex items-start gap-1.5 text-xs text-slate-300 leading-relaxed">
                            <AlertTriangle size={13} className="shrink-0 text-amber-400 mt-0.5" aria-hidden />
                            <span>{e.warnings.join(" · ")}</span>
                          </div>
                        ) : (
                          <span className="text-slate-500 text-xs">—</span>
                        )}
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
              <span className="font-medium text-slate-200">{Math.min(currentPage * PAGE_SIZE, filtered.length)}</span> of{" "}
              <span className="font-medium text-slate-200">{filtered.length}</span> candidate
              {filtered.length === 1 ? "" : "s"}
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

      {/* Candidate Inspection Modal */}
      {inspectCandidate && (
        <Modal
          open={Boolean(inspectCandidate)}
          onClose={() => setInspectCandidate(null)}
          title="Candidate Details"
          subtitle="Detailed evaluation against SpaceSentry cleanup safety policies"
        >
          <div className="space-y-4">
            {/* Full Path with 1-click Copy */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Full Windows Path
                </span>
                <CopyButton text={inspectCandidate.path} label="Copy Path" />
              </div>
              <div className="rounded-lg border border-slate-700/80 bg-surface-2 p-3 font-mono text-xs text-slate-100 select-all break-all leading-relaxed">
                {inspectCandidate.path}
              </div>
            </div>

            {/* Metadata Grid */}
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Recorded Size</span>
                <p className="mt-1 font-mono text-base font-semibold text-slate-100">
                  {formatBytes(inspectCandidate.size)}
                  <span className="ml-1.5 text-xs text-slate-400 font-normal">
                    ({inspectCandidate.size.toLocaleString()} bytes)
                  </span>
                </p>
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Classification</span>
                <div className="mt-1">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ring-1 ring-inset ${
                      CLASS_CONFIG[
                        isClassification(inspectCandidate.classification)
                          ? inspectCandidate.classification
                          : "review_required"
                      ].badgeClass
                    }`}
                  >
                    {CLASS_CONFIG[
                      isClassification(inspectCandidate.classification)
                        ? inspectCandidate.classification
                        : "review_required"
                    ].label}
                  </span>
                </div>
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Category</span>
                <p className="mt-1 text-sm font-medium text-slate-200">
                  {inspectCandidate.category}
                </p>
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
                <span className="text-[11px] uppercase tracking-wider text-slate-400">Cleanup Eligibility</span>
                <p className="mt-1 text-sm font-medium text-slate-200">
                  {inspectCandidate.eligible ? "Eligible for cleanup review" : "Ineligible for cleanup"}
                </p>
                {inspectCandidate.eligibility_detail && (
                  <p className="mt-0.5 text-xs text-slate-400">
                    {inspectCandidate.eligibility_detail}
                  </p>
                )}
              </div>
            </div>

            {/* Reason */}
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Rule Evaluation Reason
              </span>
              <p className="mt-1 text-sm text-slate-300 leading-relaxed bg-surface-2/40 p-3 rounded-lg border border-slate-800/80">
                {inspectCandidate.reason}
              </p>
            </div>

            {/* Warnings List */}
            {inspectCandidate.warnings.length > 0 && (
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
                  <AlertTriangle size={14} aria-hidden /> Safety Warnings ({inspectCandidate.warnings.length})
                </span>
                <ul className="mt-1.5 space-y-1.5">
                  {inspectCandidate.warnings.map((w, idx) => (
                    <li
                      key={idx}
                      className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-2.5 text-xs text-slate-200 flex items-start gap-2"
                    >
                      <span className="text-amber-400 font-bold">•</span>
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Canonical Path if available */}
            {inspectCandidate.canonical_path && inspectCandidate.canonical_path !== inspectCandidate.path && (
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Resolved Canonical Path
                </span>
                <p className="mt-1 font-mono text-xs text-slate-400 bg-surface-2/40 p-2.5 rounded-lg border border-slate-800/80 break-all select-all">
                  {inspectCandidate.canonical_path}
                </p>
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex justify-end pt-4 border-t border-slate-800/80">
              <Button variant="secondary" onClick={() => setInspectCandidate(null)}>
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
