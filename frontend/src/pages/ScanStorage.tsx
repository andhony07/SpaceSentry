import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FolderSearch,
  Loader2,
  StopCircle,
} from "lucide-react";
import { Button, TextInput } from "../components/ui";
import { useScanManager } from "../services/scanManager";
import { formatBytes } from "../utils/format";
import { parseRoots, validateRootInput } from "../utils/paths";

export function ScanStorage() {
  const {
    status,
    snapshot,
    beginScan,
    abortScan,
  } = useScanManager();

  const [input, setInput] = useState("C:\\Users\\yourname\\Downloads");
  const [validation, setValidation] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const running = status === "running" || status === "queued";

  async function onStart() {
    setStartError(null);
    let list: string[];
    try {
      list = parseRoots(input);
    } catch (e) {
      setValidation(e instanceof Error ? e.message : String(e));
      return;
    }
    setValidation(null);
    setStarting(true);
    try {
      await beginScan(list);
    } catch (e) {
      setStartError(`Scan request rejected by backend: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setStarting(false);
    }
  }

  // Live path-entry validation as the user types (client-side hints only;
  // the backend re-validates and rejects anything else).
  useEffect(() => {
    const err = validateRootInput(input);
    setValidation(err === null ? null : err);
  }, [input]);

  const progress = snapshot?.progress ?? null;
  const summary = snapshot?.summary ?? {
    file_count: 0,
    bytes_scanned: 0,
    skipped: { counts: {}, samples: {} },
    directory_count: 0,
    root_errors: [],
  };

  const skippedTotal = Object.values(summary.skipped.counts).reduce(
    (a, b) => a + b,
    0,
  );

  return (
    <section className="p-6 md:p-8 space-y-6" aria-labelledby="ss-title">
      {/* Header */}
      <div>
        <h1 id="ss-title" className="text-2xl font-bold tracking-tight text-slate-100">
          Scan Storage
        </h1>
        <p className="mt-1 text-sm text-slate-400 max-w-2xl">
          Initiate safe, read-only scans of local Windows directories. SpaceSentry gathers metadata and hashes without modifying, moving, or deleting any file.
        </p>
      </div>

      {/* Directory Input Form Card */}
      <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-6 shadow-sm space-y-4">
        <div>
          <label
            htmlFor="root-input"
            className="block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-1.5"
          >
            Target Directory Path (Absolute Windows Path)
          </label>
          <div className="relative">
            <TextInput
              id="root-input"
              aria-invalid={validation !== null}
              aria-describedby={validation ? "root-validation" : undefined}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={running || starting}
              placeholder="C:\\Users\\you\\Documents"
              className="font-mono text-sm"
            />
          </div>

          {validation && (
            <p id="root-validation" role="alert" className="mt-2 text-xs font-medium text-rose-400 flex items-center gap-1.5">
              <AlertTriangle size={13} aria-hidden />
              {validation}
            </p>
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Quick Suggestions:</span>
            {[
              "C:\\temp",
              "C:\\Users\\Public",
              "C:\\Users\\dell5420\\Downloads",
            ].map((p) => (
              <button
                key={p}
                type="button"
                disabled={running || starting}
                onClick={() => setInput(p)}
                className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-slate-300 transition-colors hover:bg-surface-3 hover:text-white border border-slate-700/60 disabled:opacity-50"
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <Button
            variant="primary"
            onClick={() => void onStart()}
            disabled={running || starting || validation !== null || input.trim() === ""}
          >
            {starting ? (
              <>
                <Loader2 size={16} className="animate-spin" aria-hidden />
                Requesting Scan…
              </>
            ) : (
              <>
                <FolderSearch size={16} aria-hidden />
                Start Safe Scan
              </>
            )}
          </Button>

          {running && (
            <Button
              variant="outline"
              className="border-amber-500/50 text-amber-300 hover:bg-amber-950/25"
              onClick={() => void abortScan()}
            >
              <StopCircle size={16} aria-hidden />
              Cancel In-Progress Scan
            </Button>
          )}
        </div>

        {startError && (
          <div role="alert" className="rounded-lg border border-rose-500/40 bg-rose-950/20 p-3 text-xs text-rose-300 flex items-start gap-2">
            <AlertTriangle size={15} className="shrink-0 mt-0.5" />
            <span>{startError}</span>
          </div>
        )}
      </div>

      {/* Live Progress Card when Running */}
      {progress && running && (
        <div className="rounded-xl border border-sentry-500/40 bg-sentry-950/30 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="relative flex size-2.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-sentry-400 opacity-75" />
                <span className="relative inline-flex size-2.5 rounded-full bg-sentry-400" />
              </span>
              <h2 className="text-sm font-semibold uppercase tracking-wider text-sentry-300">
                Live Scan Telemetry
              </h2>
            </div>
            <span className="text-xs font-mono text-sentry-400">Scanning in progress…</span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-sentry-800/60 bg-surface-1 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Files Traversed</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-100">
                {(progress.files_scanned ?? 0).toLocaleString()}
              </div>
            </div>
            <div className="rounded-lg border border-sentry-800/60 bg-surface-1 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Bytes Evaluated</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-100">
                {formatBytes(progress.bytes_scanned ?? 0)}
              </div>
            </div>
            <div className="rounded-lg border border-sentry-800/60 bg-surface-1 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Directories Read</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-100">
                {(progress.directories_scanned ?? 0).toLocaleString()}
              </div>
            </div>
            <div className="rounded-lg border border-sentry-800/60 bg-surface-1 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Files Skipped</div>
              <div className="mt-1 font-mono text-lg font-bold text-amber-300">
                {(progress.files_skipped ?? 0).toLocaleString()}
              </div>
            </div>
          </div>

          {progress.current_path && (
            <div className="rounded-lg border border-sentry-900/60 bg-surface-2/60 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-0.5">Current Directory</div>
              <p className="truncate font-mono text-xs text-sentry-300" title={progress.current_path}>
                {progress.current_path}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Finished Scan Summary Card */}
      {snapshot && !running && (
        <div className="rounded-xl border border-slate-800/80 bg-surface-1 p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 size={18} className="text-emerald-400" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-200">
                Scan Execution Summary
              </h2>
            </div>
            <span className="font-mono text-xs text-slate-400">
              ID: {snapshot.scan_id.slice(0, 16)}…
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Files Recorded</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-100">
                {summary.file_count.toLocaleString()}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Total Scanned Volume</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-100">
                {formatBytes(summary.bytes_scanned)}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Directories Explored</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-100">
                {summary.directory_count.toLocaleString()}
              </div>
            </div>
            <div className="rounded-lg border border-slate-800/80 bg-surface-2/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-400">Skipped / Inaccessible</div>
              <div className="mt-1 font-mono text-lg font-bold text-slate-300">
                {skippedTotal.toLocaleString()}
              </div>
            </div>
          </div>

          {(summary.root_errors?.length ?? 0) > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-950/20 p-3 text-xs text-amber-300">
              <span className="font-semibold">Some directories were inaccessible: </span>
              {summary.root_errors.join("; ")}
            </div>
          )}

          <div className="rounded-lg border border-slate-800/80 bg-surface-2/30 p-3 text-xs text-slate-400 leading-relaxed">
            <strong className="text-slate-300">Read-Only Safety Guarantee:</strong> No file was modified, moved, quarantined, or deleted during or after this scan. Results are now ready for inspection across the analysis views.
          </div>
        </div>
      )}
    </section>
  );
}
