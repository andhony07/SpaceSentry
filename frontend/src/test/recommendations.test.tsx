import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Recommendations } from "../pages/Recommendations";
import * as api from "../services/api";
import * as scanManager from "../services/scanManager";
import { formatBytes } from "../utils/format";
import type { RecommendationsResponse } from "../types";

vi.mock("../services/scanManager");

const mockRecommendationsResponse: RecommendationsResponse = {
  scan_id: "test-scan-123",
  status: "completed",
  partial: false,
  evaluations: [
    {
      path: "C:\\Users\\dell5420\\AppData\\Local\\Temp\\very_long_directory_name_with_nested_structure\\cache_artifact_001.tmp",
      canonical_path: "C:\\Users\\dell5420\\AppData\\Local\\Temp\\very_long_directory_name_with_nested_structure\\cache_artifact_001.tmp",
      size: 52428800, // 50 MB
      category: "Temporary Files",
      reason: "Matched temporary file extension (*.tmp) in AppData\\Local\\Temp",
      classification: "potential_cleanup",
      warnings: [],
      eligible: true,
      eligibility_detail: "Eligible for cleanup review according to temporary file policy.",
    },
    {
      path: "C:\\Windows\\System32\\drivers\\etc\\hosts",
      canonical_path: "C:\\Windows\\System32\\drivers\\etc\\hosts",
      size: 1024, // 1 KB
      category: "Operating System",
      reason: "Protected system path",
      classification: "protected",
      warnings: ["Operating system directory - strictly immune to automated modification"],
      eligible: false,
      eligibility_detail: "Protected system file - never eligible for cleanup.",
    },
    {
      path: "C:\\Users\\dell5420\\Downloads\\installer_setup.exe",
      canonical_path: null,
      size: 157286400, // 150 MB
      category: "Installer / Executable",
      reason: "Large downloaded installer executable",
      classification: "review_required",
      warnings: ["Executable file - verify before removing"],
      eligible: true,
      eligibility_detail: "Requires manual inspection prior to cleanup.",
    },
  ],
  counts: {
    potential_cleanup: 1,
    protected: 1,
    review_required: 1,
  },
  bytes: {
    potential_cleanup: 52428800,
    protected: 1024,
    review_required: 157286400,
  },
  by_category: {},
};

describe("Recommendations Page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();

    vi.mocked(scanManager.useScanManager).mockReturnValue({
      scanId: "test-scan-123",
      status: "completed",
      snapshot: null,
      lastError: null,
      unreachable: false,
      readyForAnalysis: true,
      beginScan: vi.fn(),
      abortScan: vi.fn(),
      clearScan: vi.fn(),
      currentRoots: ["C:\\Users\\dell5420"],
    });

    vi.spyOn(api, "getRecommendations").mockResolvedValue(mockRecommendationsResponse);
  });

  it("renders page header, stat summary tiles, and table with candidate records", async () => {
    render(<Recommendations />);

    expect(screen.getByRole("heading", { name: /cleanup recommendations/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("cache_artifact_001.tmp")).toBeInTheDocument();
      expect(screen.getByText("hosts")).toBeInTheDocument();
      expect(screen.getByText("installer_setup.exe")).toBeInTheDocument();
    });

    // Check size formatting matches formatBytes output
    expect(screen.getAllByText(formatBytes(52428800)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(formatBytes(1024)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(formatBytes(157286400)).length).toBeGreaterThan(0);

    // Check classification badges exist
    expect(screen.getAllByText("Potential cleanup").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Protected").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Review required").length).toBeGreaterThan(0);
  });

  it("filters candidate rows by classification", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);

    await waitFor(() => {
      expect(screen.getByText("cache_artifact_001.tmp")).toBeInTheDocument();
    });

    // Click "Protected" filter button
    const protectedButtons = screen.getAllByRole("button", { name: /protected/i });
    await user.click(protectedButtons[0]);

    // Only "hosts" should be visible
    await waitFor(() => {
      expect(screen.getByText("hosts")).toBeInTheDocument();
      expect(screen.queryByText("cache_artifact_001.tmp")).not.toBeInTheDocument();
      expect(screen.queryByText("installer_setup.exe")).not.toBeInTheDocument();
    });
  });

  it("filters candidate rows by path search query", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);

    await waitFor(() => {
      expect(screen.getByText("cache_artifact_001.tmp")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/filter candidates by path/i);
    await user.type(searchInput, "installer");

    await waitFor(() => {
      expect(screen.getByText("installer_setup.exe")).toBeInTheDocument();
      expect(screen.queryByText("cache_artifact_001.tmp")).not.toBeInTheDocument();
      expect(screen.queryByText("hosts")).not.toBeInTheDocument();
    });
  });

  it("opens candidate inspect modal when inspect button is clicked", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);

    await waitFor(() => {
      expect(screen.getByText("cache_artifact_001.tmp")).toBeInTheDocument();
    });

    const inspectButtons = screen.getAllByTitle(/inspect full candidate details/i);
    await user.click(inspectButtons[0]);

    await waitFor(() => {
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(within(dialog).getByText("Candidate Details")).toBeInTheDocument();
      expect(within(dialog).getByText(/52,428,800 bytes/)).toBeInTheDocument();
      expect(within(dialog).getByText(/matched temporary file extension/i)).toBeInTheDocument();
    });
  });

  it("renders ErrorPanel when API fails", async () => {
    vi.spyOn(api, "getRecommendations").mockRejectedValue(new Error("Network timeout"));

    render(<Recommendations />);

    await waitFor(() => {
      expect(screen.getByText("Could not load cleanup recommendations")).toBeInTheDocument();
      expect(screen.getByText("Network timeout")).toBeInTheDocument();
    });
  });
});
