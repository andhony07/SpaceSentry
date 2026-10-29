import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CopyButton, Modal, StatTile, ScanStatusBadge } from "../components/ui";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableCell,
  TablePath,
} from "../components/ui/table";

describe("UI Components", () => {
  describe("Semantic Table", () => {
    it("renders semantic table, thead, th, tbody, tr, td elements", () => {
      render(
        <Table data-testid="test-table">
          <TableHeader>
            <TableRow>
              <TableCell>Candidate Path</TableCell>
              <TableCell className="text-right">Size</TableCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>
                <TablePath>C:\Users\test\file.tmp</TablePath>
              </TableCell>
              <TableCell className="text-right font-mono">1.2 MB</TableCell>
            </TableRow>
          </TableBody>
        </Table>,
      );

      const table = screen.getByTestId("test-table");
      expect(table.tagName).toBe("TABLE");

      const ths = screen.getAllByRole("columnheader");
      expect(ths).toHaveLength(2);
      expect(ths[0].tagName).toBe("TH");
      expect(ths[0]).toHaveTextContent("Candidate Path");
      expect(ths[1]).toHaveTextContent("Size");
      expect(ths[1]).toHaveClass("text-right");

      const cells = screen.getAllByRole("cell");
      expect(cells).toHaveLength(2);
      expect(cells[0].tagName).toBe("TD");
      expect(cells[1].tagName).toBe("TD");
      expect(cells[1]).toHaveClass("text-right font-mono");
    });
  });

  describe("CopyButton", () => {
    it("copies text and updates label on click", async () => {
      const user = userEvent.setup();
      const mockWriteText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText: mockWriteText },
        configurable: true,
        writable: true,
      });

      render(<CopyButton text="C:\Windows\System32\drivers\etc\hosts" label="Copy" />);

      const button = screen.getByRole("button", { name: /copy path/i });
      expect(button).toBeInTheDocument();

      await user.click(button);

      expect(mockWriteText).toHaveBeenCalledWith("C:\\Windows\\System32\\drivers\\etc\\hosts");
      await waitFor(() => {
        expect(screen.getByText("Copied")).toBeInTheDocument();
      });
    });
  });

  describe("Modal", () => {
    it("renders dialog contents when open and closes on close button", async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();

      const { rerender } = render(
        <Modal open={false} onClose={onClose} title="Inspect Candidate">
          <p>Candidate Information</p>
        </Modal>,
      );

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

      rerender(
        <Modal open={true} onClose={onClose} title="Inspect Candidate">
          <p>Candidate Information</p>
        </Modal>,
      );

      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(screen.getByText("Inspect Candidate")).toBeInTheDocument();
      expect(screen.getByText("Candidate Information")).toBeInTheDocument();

      const closeButton = screen.getByRole("button", { name: /close dialog/i });
      await user.click(closeButton);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("triggers onClose on Escape key press", () => {
      const onClose = vi.fn();
      render(
        <Modal open={true} onClose={onClose} title="Inspect Candidate">
          <p>Candidate Information</p>
        </Modal>,
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("StatTile and ScanStatusBadge", () => {
    it("renders StatTile with label, value, and hint", () => {
      render(
        <StatTile
          label="Potential Cleanup"
          value="42 candidates"
          hint="Reclaimable files"
        />,
      );

      expect(screen.getByText("Potential Cleanup")).toBeInTheDocument();
      expect(screen.getByText("42 candidates")).toBeInTheDocument();
    });

    it("renders status badge with running and completed states", () => {
      const { rerender } = render(<ScanStatusBadge status="running" />);
      expect(screen.getByText("running")).toBeInTheDocument();

      rerender(<ScanStatusBadge status="completed" />);
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });
});
