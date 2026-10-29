# SpaceSentry — Safe Storage Intelligence

SpaceSentry helps Windows users understand what consumes their disk space,
discover potentially reclaimable files, and safely reclaim storage only after
reviewing and approving the proposed actions.

> **Status: Phase 4 — Safe Cleanup and Quarantine complete.**
> Full lifecycle implemented: read-only scanning (Phase 1), deterministic analysis
> (Phase 2), cleanup recommendations, explicit approval, quarantine, restoration,
> and audit history. All 108 backend tests pass, 16 frontend tests pass, TypeScript
> compilation exits cleanly, and production build succeeds.

> **Safety model:** Cleanup never deletes permanently by default. Quarantine moves
> files to a dedicated non-operation directory with fail-safe collision avoidance.
> Every action revalidates canonical paths, file identity (size + mtime_ns),
> reparse-point status, and approved-root containment. Session tokens are single-use
> and short-lived. Restoration refuses to overwrite existing destinations.

> **Verified:** All 108 backend tests pass, 16 frontend tests pass, TypeScript compilation
> exits 0, production build succeeds. Cleanup API covers preview, approval, quarantine,
> restore, authorization expiry/reuse, collision refusal, and restore conflicts.

## Safety principles

- **Read-only scanning.** The scanner only lists and stats files; it never
  opens, moves, renames, or deletes anything.
- **Root-bounded traversal.** Only user-selected directories are scanned.
- **Reparse-safe.** Symlinks and junctions (reparse points) are skipped by
  default to prevent unintended traversal outside approved boundaries.
- **Loop-safe.** Directory cycles are detected via `(st_dev, st_ino)` identity
  plus a hard depth limit.
- **No auto-deletion.** Cleanup will require explicit per-item user approval,
  backend revalidation of every path, and rejection of protected locations.
- **Localhost only.** The API binds to `127.0.0.1` with a restricted CORS
  allowlist. No data leaves the machine.

## Structure

```
SpaceSentry/
  backend/        FastAPI backend (scanner, analysis, cleanup policy — later phases)
  docs/           Categorization rules and safety documentation
  frontend/       React + TypeScript + Vite + Tailwind (Phase 3)
  tests/          Pytest (backend) and Vitest (frontend)
  docs/           Architecture and safety documentation
```

## Setup (backend)

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Run the API:

```bash
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Run the tests (from the repository root):

```bash
backend\.venv\Scripts\python -m pytest tests/backend -q
```

See `.env.example` for configuration variables.

## License

Hackathon project for Next Byte Hacks V5.
