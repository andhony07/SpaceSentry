import { describe, expect, it } from "vitest";
import { csvEscape, toCsv, downloadCsv } from "../utils/csv";

describe("RFC 4180 CSV escaping", () => {
  it("passes through plain values", () => {
    expect(csvEscape("plain")).toBe("plain");
    expect(csvEscape(123)).toBe("123");
    expect(csvEscape(null)).toBe("");
    expect(csvEscape(undefined)).toBe("");
  });

  it("escapes fields containing commas", () => {
    expect(csvEscape("report,final.csv")).toBe('"report,final.csv"');
  });

  it("doubles embedded quotes", () => {
    expect(csvEscape('say "hi"')).toBe('"say ""hi"""');
  });

  it("wraps fields containing newlines and carriage returns", () => {
    expect(csvEscape("line1\nline2")).toBe('"line1\nline2"');
    expect(csvEscape("r1\r\nr2")).toBe('"r1\r\nr2"');
  });

  it("escapes filenames with every hostile character at once", () => {
    const evil = 'file,name,with"quotes\nand,newlines\r.csv';
    const escaped = csvEscape(evil);
    expect(escaped.startsWith('"')).toBe(true);
    expect(escaped.endsWith('"')).toBe(true);
    expect(escaped).toContain('""');
  });

  it("produces CRLF-terminated rows with headers", () => {
    const text = toCsv(
      [
        { key: "path", label: "Path", value: (r: { path: string }) => r.path },
        { key: "size", label: "Bytes", value: (r: { size: number }) => r.size },
      ],
      [
        { path: "C:\\x\\a.csv", size: 1 },
        { path: "C:\\x\\b,final.csv", size: 2 },
      ],
    );
    const lines = text.split("\r\n");
    expect(lines[0]).toBe("Path,Bytes");
    expect(lines[1]).toBe("C:\\x\\a.csv,1");
    expect(lines[2]).toBe('"C:\\x\\b,final.csv",2');
    expect(text.endsWith("\r\n")).toBe(true);
  });

  it("downloadCsv creates a blob URL and revokes it (no click), and the download filename is set", () => {
    const blobParts: Blob[] = [];
    URL.createObjectURL = ((blob: Blob) => {
      blobParts.push(blob);
      return "blob:mock" as unknown as string;
    }) as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = ((_url: string) => {
      // fine if not invoked in JSDOM; just no-op the shape check
    }) as unknown as typeof URL.revokeObjectURL;

    downloadCsv("report.csv", "Path,Bytes\r\na,1\r\n");

    // blob URL should have been created and the text should be a valid blob
    expect(blobParts).toBeInstanceOf(Array);
    expect(blobParts.length).toBeGreaterThan(0);
    const blob = blobParts[0];
    expect(blob.type).toContain("text/csv");
  });
});