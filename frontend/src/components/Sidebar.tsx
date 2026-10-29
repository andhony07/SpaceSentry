import type { ReactNode } from "react";
import {
  BarChart3,
  CopyX,
  FolderSearch,
  HardDrive,
  Eye,
  ScrollText,
  Shield,
  X,
} from "lucide-react";
import { useScanManager } from "../services/scanManager";
import { ScanStatusBadge } from "./ui";

export type ViewKey =
  | "overview"
  | "scan"
  | "large"
  | "duplicates"
  | "recommendations"
  | "reports";

const NAV: { key: ViewKey; label: string; icon: ReactNode }[] = [
  { key: "overview", label: "Overview", icon: <HardDrive size={18} aria-hidden /> },
  { key: "scan", label: "Scan Storage", icon: <FolderSearch size={18} aria-hidden /> },
  { key: "large", label: "Large Files", icon: <Eye size={18} aria-hidden /> },
  { key: "duplicates", label: "Duplicates", icon: <CopyX size={18} aria-hidden /> },
  { key: "recommendations", label: "Cleanup Recommendations", icon: <Shield size={18} aria-hidden /> },
  { key: "reports", label: "Reports", icon: <ScrollText size={18} aria-hidden /> },
];

export function Sidebar({
  active,
  onNavigate,
  mobileOpen = false,
  onMobileClose,
}: {
  active: ViewKey;
  onNavigate: (view: ViewKey) => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}) {
  const { status, scanId } = useScanManager();

  const handleSelect = (key: ViewKey) => {
    onNavigate(key);
    if (onMobileClose) {
      onMobileClose();
    }
  };

  return (
    <>
      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-xs md:hidden"
          onClick={onMobileClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar container */}
      <aside
        aria-label="Sidebar navigation"
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-sentry-900/60 bg-sentry-950 transition-transform duration-200 ease-in-out md:static md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        {/* Brand Header */}
        <div className="flex h-16 items-center justify-between border-b border-sentry-900/60 px-5">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-sentry-600/25 ring-1 ring-sentry-500/40 shadow-sm">
              <BarChart3 size={20} className="text-sentry-300" aria-hidden />
            </div>
            <div>
              <div className="text-sm font-bold tracking-wide text-white">SpaceSentry</div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-sentry-300/70">
                Safe Storage Intelligence
              </div>
            </div>
          </div>
          {onMobileClose && (
            <button
              type="button"
              onClick={onMobileClose}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-sentry-900/60 hover:text-white md:hidden"
              aria-label="Close menu"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Navigation Items */}
        <nav aria-label="Main navigation" className="flex-1 overflow-y-auto px-3 py-4">
          <div className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-sentry-300/60">
            Navigation
          </div>
          <ul className="space-y-1">
            {NAV.map((item) => {
              const isActive = active === item.key;
              return (
                <li key={item.key}>
                  <button
                    type="button"
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => handleSelect(item.key)}
                    className={`group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all ${
                      isActive
                        ? "bg-sentry-800/80 text-white shadow-sm ring-1 ring-sentry-600/50"
                        : "text-slate-300 hover:bg-sentry-900/50 hover:text-white"
                    }`}
                  >
                    <span
                      className={`transition-colors ${
                        isActive
                          ? "text-sentry-300"
                          : "text-slate-400 group-hover:text-slate-200"
                      }`}
                    >
                      {item.icon}
                    </span>
                    <span className="truncate">{item.label}</span>
                    {isActive && (
                      <span className="ml-auto size-1.5 rounded-full bg-sentry-400" aria-hidden />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Current Scan Status Footer */}
        <div className="border-t border-sentry-900/60 p-4">
          <div className="rounded-xl border border-sentry-800/50 bg-sentry-900/40 p-3 shadow-xs">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-sentry-300/70">
                Scan Status
              </span>
              <ScanStatusBadge status={status} />
            </div>

            <div className="text-[11px] text-slate-300">
              {status === "idle" && (
                <span className="text-slate-400">Ready to initiate scan</span>
              )}
              {(status === "running" || status === "queued") && (
                <span className="text-sentry-300 flex items-center gap-1.5">
                  <span className="size-1.5 animate-pulse rounded-full bg-sentry-400" />
                  Scan in progress…
                </span>
              )}
              {status === "completed" && (
                <span className="text-emerald-400">Scan finished successfully</span>
              )}
              {status === "cancelled" && (
                <span className="text-amber-400">Scan cancelled (partial data)</span>
              )}
              {status === "failed" && (
                <span className="text-rose-400">Scan encountered an error</span>
              )}
            </div>

            {scanId && (
              <div className="mt-2 pt-2 border-t border-sentry-800/40 font-mono text-[10px] text-slate-400 truncate" title={`Active Scan ID: ${scanId}`}>
                ID: {scanId.slice(0, 12)}…
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
