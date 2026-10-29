# SpaceSentry categorization and safety rules (Phase 2)

This document is the single source of truth for how SpaceSentry decides what
to flag. Every rule below is implemented deterministically in
[backend/app/services/categorizer.py](../backend/app/services/categorizer.py).
No AI or heuristic guessing: a finding exists **only** if a documented rule
matched.

## Golden rules

1. **Analysis is read-only.** Scanning lists and stats files; duplicate
   detection additionally *reads* file contents to hash them. Nothing is
   deleted, moved, renamed, or written at any point in Phase 2.
2. **Size and age are never safety signals.** Finding that a file is large
   or old never suggests it is safe to delete.
3. **Unknown means review.** A file matched by no rule is `uncategorized`
   and classified `review_required`.
4. **Content decides duplicates.** Two files are duplicates only if their
   SHA-256 digests match — never by filename, extension, or size.

## Categories and exact rules

| ID | Category | Rule (documented) | Default threshold |
|----|----------|-------------------|-------------------|
| T1 | `temporary_file` | File extension is in `{.tmp, .temp, .crdownload, .partial}` | — |
| B1 | `dev_build_cache` | Any parent directory name is an unambiguous tool-owned cache dir: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.vite`, `.parcel-cache`, `.turbo` | — |
| B2 | `dev_build_cache` (review-only flavor) | Parent dir name in ambiguous set: `build`, `dist`, `obj`, `bin`, `out`, `target`, `node_modules` | — |
| B3 | `dev_build_cache` | Extension in `{.pyc, .pyo, .class, .obj, .o}` | — |
| D1 | `potential_duplicate` | File's SHA-256 equals another scanned file's SHA-256 (see duplicate pipeline below) | — |
| L1 | `large_file` | Recorded size ≥ threshold | 100 MiB (configurable) |
| O1 | `old_file` | Modification time ≤ `now - N days` | 365 days (configurable) |
| U1 | `uncategorized` | No rule above matched | — |

Deliberate exclusions: `.log`, `.exe`, `.zip`, generic names like `tmp`/
`temp` as *directory* names alone, and any content-signature guessing are
**not** used. Generic extensions are too ambiguous to treat as cleanup
signals. Use the Unclassified/Large tables for human review.

A file can accumulate several findings (e.g. `.tmp` extension inside a
`__pycache__`, and also a verified duplicate). Multiple findings do not make
a file "more deletable".

## Duplicate detection pipeline

Implemented in [duplicate_detector.py](../backend/app/services/duplicate_detector.py):

1. **Stage 1 — size pre-filter.** Scan-recorded files are grouped by exact
   byte size. Groups with fewer than two files are ignored. This is a cheap
   pre-filter, never evidence.
2. **Stage 2 — revalidation then hash.** Largest groups first, each file:
   - `stat` (no symlink following): reparse points are excluded outright;
   - the current size + mtime must match the scan-time record, else the file
     is excluded as `changed_since_scan`;
   - SHA-256 is computed by streaming 64 KiB chunks (large files are never
     fully loaded into memory), bounded by a per-run hash budget
     (default 1 GiB; larger groups are reported as `budget_exceeded`);
   - `stat` again: metadata changed mid-hash ⇒ excluded as
     `changed_during_hash` (its digest cannot be trusted);
   - read errors ⇒ `unreadable`; vanished mid-run ⇒ `disappeared`.
3. **Stage 3 — verify.** A group is reported only when the compared digests
   match. `reclaimable_if_one_copy_removed` equals size × (copies − 1): the
   maximum bytes that would be freed **if** the user removed all but one
   copy. Nobody removes anything in this phase.

## Cleanup policy classifications

Implemented in [cleanup_policy.py](../backend/app/services/cleanup_policy.py).
Every finding receives exactly one classification:

- **`potential_cleanup`** — only when a *narrow* documented rule matched
  (currently: T1 temporary extensions, D1 verified duplicates), all path
  protection checks pass, AND the candidate is verifiable right now: a
  candidate that is missing on disk or that resolves to a directory can be
  labeled `potential_cleanup` (the rule matched) but is always
  `eligible=false` with an explicit reason. Directories are additionally
  demoted to `review_required`. Always carries explicit warnings ("keep at
  least one copy of every duplicate group").
- **`review_required`** — everything ambiguous or unmatched: large files,
  old files, ambiguous build dir contents, `uncategorized`, artifacts.
- **`protected`** — never selectable. Applied when the path fails any of:
  - **Approved-roots containment:** the canonical path must lie inside one
    of the user-approved scan roots. Anything outside (including
    `..`-escaped paths and other drives) is protected.
  - **Windows system/application locations:** `SystemRoot`/`windir`
    (`C:\Windows`), `Program Files`, `Program Files (x86)`, `ProgramData`,
    per-drive `$Recycle.Bin` / `System Volume Information`.
  - **Protected system files:** `pagefile.sys`, `hiberfil.sys`,
    `swapfile.sys`, `memory.dmp` at drive roots.
  - **Reparse points:** symlinks/junctions are excluded from cleanup.
  - **UNC paths:** unverifiable against local approved roots ⇒ protected.
  - **Unresolvable canonical path:** if `realpath` cannot verify the file,
    it is protected, never guessed.

All checks run against the **canonical path** (`os.path.realpath`, normcased)
— never the recorded string — so look-alike spellings cannot bypass policy.

## Hardening added during the Phase 2 security audit

- **Post-open identity guard (TOCTOU):** duplicate hashing opens files with
  `O_NOFOLLOW` (where supported) and verifies the open handle's
  `(st_dev, st_ino)` identity against the pre-open stat; a file swapped
  between stat and open is excluded as `swapped_during_open` and never
  hashed.
- **Approved-root canonicalization:** containment is checked against the
  realpath-resolved root, so a root later replaced by a junction cannot
  widen the trust boundary.
- **Loopback host/origin guard:** the API rejects requests whose `Host`
  header is not `127.0.0.1` / `localhost` / `::1` (DNS-rebinding protection)
  and requests carrying an `Origin` header outside the allowlist (simple
  cross-site request protection) with HTTP 403.
- **Partial-analysis marker:** all analysis endpoints return
  `partial: true` when computed from a *cancelled* (partially traversed)
  scan, so incomplete data can never be mistaken for a complete sweep.

## Current limitations

- Classifications are advisory; there is **no deletion of any kind yet**.
  Phase 4 will add execution, gated by explicit per-item approval and
  immediate re-evaluation against this same policy immediately before any
  destructive step.
- Categorization covers explicit local rules only; "known cache location"
  checks apply to directory-name rules inside the scanned tree, not to
  operating-system cache folders outside scanned roots.
- Hash budget: a duplicate run hashes at most 1 GiB by default; larger
  candidates are reported, not silently skipped.
- Readonlyness of *atime*: platform-dependent (Windows defaults to disabled
  updates); SpaceSentry never asserts atime preservation.

## API usage

All analysis endpoints are GET-only under an existing scan id:

```
GET /api/scans/{scan_id}/analysis/large-files?min_size_bytes=&limit=
GET /api/scans/{scan_id}/analysis/duplicates?hash_budget_bytes=
GET /api/scans/{scan_id}/analysis/findings?old_days=&large_threshold_bytes=
GET /api/scans/{scan_id}/analysis/recommendations?old_days=&large_threshold_bytes=
```

Returns `404` for unknown scan ids and `409` while the scan is still
running (analysis on partial data would be misleading). All numbers in the
responses come from real scan records on disk.
