/**
 * CSV serialization for real scan/analysis data.
 *
 * RFC 4180 quoting: quotes are doubled, fields containing commas, quotes,
 * carriage returns or newlines are wrapped in double quotes. Line endings
 * use \r\n for Excel compatibility.
 */

export type CsvScalar = string | number | boolean | null | undefined;

export type CsvRow = Record<string, CsvScalar>;

export function csvEscape(value: CsvScalar): string {
  if (value === null || value === undefined) return "";
  const s = typeof value === "string" ? value : String(value);
  if (/[",\r\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

export interface CsvColumnSpec<R> {
  key: string;
  label: string;
  value: (row: R) => CsvScalar;
}

/** Serialize rows with a declared column order. */
export function toCsv<T>(columns: Array<CsvColumnSpec<T>>, rows: readonly T[]): string {
  const head = columns.map((c) => csvEscape(c.label)).join(",");
  const bodyLines = rows.map(
    (row) => columns.map((c) => csvEscape(c.value(row))).join(","),
  );
  return [head, ...bodyLines].join("\r\n") + "\r\n";
}

/** Trigger a browser download of CSV text. */
export function downloadCsv(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
