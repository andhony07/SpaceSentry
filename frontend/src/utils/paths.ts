/**
 * Client-side validation hints for the Scan Storage path input.
 *
 * These are convenience hints only — they intentionally mirror the backend's
 * documented rules (app/core/paths.py) but the backend re-validates every
 * submitted root and rejects anything unsafe regardless of this UI.
 */

const PLACEHOLDER = /^C:\\Users\\yourname\\/i;

export function validateRootInput(value: string): string | null {
  if (value.trim() === "") return null; // nothing entered yet
  if (PLACEHOLDER.test(value.trim())) {
    return "This is the example placeholder — replace it with a directory you actually own.";
  }
  if (value.includes("\n") || value.includes("\r")) return null; // multi-editor line, not an error here
  const trimmed = value.trim();
  if (/^\\\\/.test(trimmed)) {
    return "UNC network paths are not accepted as scan roots.";
  }
  if (!/^[A-Za-z]:\\/.test(trimmed)) {
    return "Enter a Windows absolute path with a drive letter, e.g. C:\\Users\\you\\Documents.";
  }
  if (/[<>|?*\u0000-\u001f"]/.test(trimmed)) {
    return "Path contains characters Windows does not allow in paths.";
  }
  return null;
}

/** Parse the input box contents into a root list to submit. */
export function parseRoots(input: string): string[] {
  const roots = input
    .split(/[\r\n]+/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (roots.length === 0) throw new Error("Enter at least one directory.");
  if (roots.length > 8) throw new Error("At most 8 directories per scan.");
  return roots;
}
