import { useState } from "react";
import { FolderSearch, Menu } from "lucide-react";
import { ScanManagerProvider, useScanManager } from "./services/scanManager";
import { Sidebar, type ViewKey } from "./components/Sidebar";
import { Overview } from "./pages/Overview";
import { ScanStorage } from "./pages/ScanStorage";
import { LargeFiles } from "./pages/LargeFiles";
import { Duplicates } from "./pages/Duplicates";
import { Recommendations } from "./pages/Recommendations";
import { Reports } from "./pages/Reports";
import { Button, EmptyState } from "./components/ui";

function View({
  view,
  onNavigate,
}: {
  view: ViewKey;
  onNavigate: (view: ViewKey) => void;
}) {
  const { readyForAnalysis, snapshot } = useScanManager();

  if (!readyForAnalysis) {
    switch (view) {
      case "large":
      case "duplicates":
      case "recommendations":
      case "reports":
        return (
          <EmptyAnalysisGate
            scanRunning={snapshot?.status === "running" || snapshot?.status === "queued"}
            onNavigate={onNavigate}
          />
        );
      default:
        break;
    }
  }

  switch (view) {
    case "overview":
      return <Overview onNavigate={onNavigate} />;
    case "scan":
      return <ScanStorage />;
    case "large":
      return <LargeFiles />;
    case "duplicates":
      return <Duplicates />;
    case "recommendations":
      return <Recommendations />;
    case "reports":
      return <Reports />;
  }
}

function EmptyAnalysisGate({
  scanRunning,
  onNavigate,
}: {
  scanRunning: boolean;
  onNavigate: (view: ViewKey) => void;
}) {
  return (
    <div className="p-6 md:p-8 max-w-2xl mx-auto">
      <EmptyState
        icon={<FolderSearch size={28} className="text-sentry-400" />}
        title="Analysis needs a finished scan"
        description={
          scanRunning
            ? "A scan is currently running in the background. Analysis findings, candidate evaluations, and reports will become available here once it completes or is cancelled."
            : "No completed scan is available in this session yet. Open Scan Storage, choose a directory you own, and start a read-only scan to populate this analysis."
        }
        action={
          <Button
            variant="primary"
            onClick={() => onNavigate("scan")}
          >
            Go to Scan Storage
          </Button>
        }
      />
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<ViewKey>("overview");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <ScanManagerProvider>
      <div className="flex h-screen bg-surface-0 overflow-hidden">
        {/* Sidebar */}
        <Sidebar
          active={view}
          onNavigate={setView}
          mobileOpen={mobileMenuOpen}
          onMobileClose={() => setMobileMenuOpen(false)}
        />

        {/* Main Content Area */}
        <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
          {/* Mobile Top Header */}
          <header className="flex h-14 items-center justify-between border-b border-slate-800/80 bg-surface-1 px-4 md:hidden">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="rounded-lg p-2 text-slate-300 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sentry-400"
              aria-label="Open navigation menu"
            >
              <Menu size={20} />
            </button>
            <span className="text-sm font-bold tracking-wide text-white">SpaceSentry</span>
            <div className="w-8" />
          </header>

          {/* Scrollable Page Body */}
          <main className="min-w-0 flex-1 overflow-y-auto">
            <View view={view} onNavigate={setView} />
          </main>
        </div>
      </div>
    </ScanManagerProvider>
  );
}
