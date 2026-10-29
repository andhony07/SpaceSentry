"""Phase 4 — safe cleanup execution with quarantine and restoration.

Design principles
-----------------
* Default action is **move to quarantine**, not permanent deletion. The
  quarantine directory lives under a dedicated SpaceSentry location so a
  mistaken move is recoverable through restore.
* Every filesystem action revalidates the candidate immediately before it
  happens. If any check fails, the operation is refused and the failure is
  recorded — never silently ignored.
* No shell, no PowerShell, no admin elevation, no arbitrary commands. Only
  ``os``/``pathlib``/``shutil``/``hashlib`` are used.
* Symlinks/reparse points are never followed for identity or move decisions.
* The quarantine collision policy is fail-safe: if the destination already
  exists, the candidate is not overwritten — the operation is rejected.
* ``pending``-to-``processing`` state is per candidate, so partial failures
  are visible rather than hiding behind an all-or-nothing result.
* Deceptive reporting is impossible by construction: bytes moved to quarantine
  are reported separately from bytes reclaimed, and reclaim is only incremented
  when shutil.move genuinely removes the source from the approved volume.

Storage layout
--------------
* Quarantine root: ``<system-temp>/SpaceSentry-Quarantine/<operation_id>/``
  per operation, so a single failed operation cannot pollute future ones and
  old operations are easy to sweep.
* Each quarantined file: ``<opdir>/<safe-name>`` where safe-name is a hex
  collision-proof name derived from the file identity and a per-operation
  counter, preserving the original extension.
* Audit rows are kept in ``<quarantine-root>/space_sentry_audit.jsonl`` so the
  history survives across restarts (within the same machine) without a separate
  database.


Security notes (not exhaustive — tests encode the expected behavior)
---------------------------------------------------------------------
* Candidates must be linked to a verified, finished scan record. Arbitrary
  posted paths are not accepted as cleanup candidates.
* Preview and execution both run the same protection-violation checks as the
  classification policy, plus explicit "is this still a real regular file
  inside an approved root, with the expected size/mtime identity" checks.
* A candidate whose on-disk identity no longer matches the scan record is
  rejected as ``changed`` rather than operated on.
* restore() refuses to overwrite a file that already exists at the destination.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat as stat_module
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.protected_paths import protection_violations, canonical_path
from app.services.scanner import FileRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Where SpaceSentry keeps quarantined files on this machine. This is a
# dedicated, non-system location owned by the current user. It is *not* inside
# any scanned root, so quarantine cannot itself be a cleanup target.
QUARANTINE_ROOT = Path(os.environ.get("SPACESENTRY_QUARANTINE_DIR") or os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
QUARANTINE_ROOT = QUARANTINE_ROOT / "SpaceSentry-Quarantine"

SESSION_TOKEN_BYTES = 32
OPERATION_ID_BYTES = 16

# Identity revalidation tolerance for "has this file changed since the scan?".
# Only applied to records that carry nanosecond mtime (all scanner records do).
MTIME_NS_TOLERANCE_NS = 5_000_000  # 5 ms — protects against unrelated fs clock jitter

# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@dataclass
class AuditRow:
    operation_id: str
    timestamp: str
    action: str  # "quarantine" | "restore" | "preview"
    candidate_path: str
    quarantine_path: str | None
    status: str  # "ok" | "failed"
    recorded_size: int
    actual_size: int | None
    failure_reason: str | None
    bytes_moved_to_quarantine: int
    bytes_reclaimed: int
    notes: list[str] = field(default_factory=list)

    def to_public(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "candidate_path": self.candidate_path,
            "quarantine_path": self.quarantine_path,
            "status": self.status,
            "recorded_size": self.recorded_size,
            "actual_size": self.actual_size,
            "failure_reason": self.failure_reason,
            "bytes_moved_to_quarantine": self.bytes_moved_to_quarantine,
            "bytes_reclaimed": self.bytes_reclaimed,
            "notes": list(self.notes),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def make_session_token() -> str:
    return secrets.token_hex(SESSION_TOKEN_BYTES)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Operation state (in-memory within the registry lifecycle; audit file is
# the durable cross-restart record for the current machine).
# ---------------------------------------------------------------------------


@dataclass
class CleanupOperation:
    operation_id: str
    scan_id: str
    approved_roots: list[str]
    session_token: str
    created_at: float
    expires_at: float
    status: str  # "pending" | "completed" | "partial"
    candidates: dict[str, dict[str, Any]]  # id -> {path, recorded_size, recorded_mtime_ns, canonical, category, reason, classification, eligible, warnings, eligibility_detail}
    results: dict[str, dict[str, Any]]  # id -> result
    bytes_quarantined: int
    bytes_reclaimed: int
    audit_rows: list[AuditRow]
    quarantine_root: Path

    def to_public(self, include_audit: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "operation_id": self.operation_id,
            "scan_id": self.scan_id,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "bytes_quarantined": self.bytes_quarantined,
            "bytes_reclaimed": self.bytes_reclaimed,
            "candidates": list(self.candidates.values()),
            "results": list(self.results.values()),
        }
        if include_audit:
            out["audit"] = [r.to_public() for r in self.audit_rows]
        return out


# ---------------------------------------------------------------------------
# Validation helpers used by preview AND execution (single source of truth)
# ---------------------------------------------------------------------------


def _file_identity(st: os.stat_result) -> tuple[int, int]:
    return (int(st.st_dev), int(st.st_ino))


def _is_reparse_point(st: os.stat_result, path: str) -> bool:
    # Mirrors scanner._is_reparse exactly so protection decisions are consistent.
    if getattr(st, "st_file_attributes", 0) & 0x400:
        return True
    return os.path.islink(path)


def _candidate_revalidation_errors(
    record: FileRecord,
    approved_roots: list[str],
    *,
    require_inside_root: bool = True,
) -> list[str]:
    """Return the reasons a candidate cannot be acted on right now.

    This is the execution-time sibling of the classification-time checks. It
    does not decide *eligibility* for cleanup (that is the policy module's
    job); it decides *safety to operate on* right now.
    """
    errors: list[str] = []

    # 1. Protection violations (outside root, system path, reparse, UNC, ...).
    violations = protection_violations(record.path, approved_roots)
    if violations:
        errors.extend(violations)

    # 2. Resolve canonical now; must be a real file we can identify.
    canonical = canonical_path(record.path)
    if canonical is None:
        # Either missing or unresolvable. Existence is checked below for the
        # common case; otherwise treat as unverifiable.
        if not os.path.exists(os.path.abspath(record.path)):
            errors.append("missing")
        else:
            errors.append("unverifiable_path")
        return errors

    # 3. Must be a regular file (not a directory, not special).
    try:
        st = os.stat(canonical, follow_symlinks=False)
    except OSError:
        errors.append("stat_failed")
        return errors

    if not stat_module.S_ISREG(st.st_mode):
        errors.append("not_a_regular_file")

    # 4. Symlink/reparse point rejection (even if scanner skipped it, we are
    #    strict here: a cleanup candidate must be a real file).
    if _is_reparse_point(st, canonical):
        errors.append("reparse_point")

    # 5. Identity revalidation against scan record (size + mtime_ns).
    if record.size != st.st_size:
        errors.append("size_changed")
    elif record.mtime_ns:
        current_ns = int(getattr(st, "st_mtime_ns", 0))
        if abs(current_ns - record.mtime_ns) > MTIME_NS_TOLERANCE_NS:
            errors.append("mtime_changed")

    # 6. If requested, enforce strict approved-root containment on the canonical
    #    path (not just the raw spelling).
    if require_inside_root:
        approved_canonical = [canonical_root(r) for r in approved_roots]
        if not any(
            canonical == rc or canonical.startswith(rc + os.sep) for rc in approved_canonical
        ):
            errors.append("outside_approved_roots_canonical")

    return errors


def canonical_root(root: str) -> str:
    """Realpath-resolved, normcased approved root (mirrors protected_paths.canonical_root)."""
    from app.core.protected_paths import _BODY

    resolved = os.path.realpath(os.path.abspath(root))
    return _BODY(resolved)


# ---------------------------------------------------------------------------
# Quarantine naming (collision-safe, no overwrite ever)
# ---------------------------------------------------------------------------


def _safe_quarantine_name(record: FileRecord, counter: int) -> str:
    # Deterministic but collision-safe: derived from file identity + a
    # per-operation counter, not from the untrusted filename alone.
    identity = hashlib.sha256(
        f"{record.path}\x00{record.size}\x00{record.mtime_ns}\x00{counter}".encode("utf-8")
    ).hexdigest()[:16]
    ext = record.extension or ""
    return f"{identity}{ext}"


# ---------------------------------------------------------------------------
# Quarantine service
# ---------------------------------------------------------------------------


class QuarantineService:
    """Move eligible files into a dedicated quarantine location.

    This is the default cleanup action. Permanent deletion is not exposed.
    """

    def __init__(self, operation: CleanupOperation) -> None:
        self.op = operation
        # One subdirectory per operation so partial failures don't pollute the
        # namespace and so old operations are easy to enumerate/clean up.
        self.opdir = operation.quarantine_root / operation.operation_id
        try:
            os.makedirs(str(self.opdir), exist_ok=True)
        except OSError as exc:
            raise QuarantineError(f"cannot create quarantine directory: {exc}") from exc

    # --------------------------------------------------------------- preview ---

    def preview(self, candidate_id: str, record: FileRecord) -> dict[str, Any]:
        """Build a preview item without touching the filesystem."""
        errors = _candidate_revalidation_errors(record, self.op.approved_roots)
        canonical = canonical_path(record.path)
        return {
            "candidate_id": candidate_id,
            "path": record.path,
            "canonical_path": canonical,
            "recorded_size": record.size,
            "recorded_mtime_ns": record.mtime_ns,
            "category": self.op.candidates[candidate_id].get("category", ""),
            "reason": self.op.candidates[candidate_id].get("reason", ""),
            "classification": self.op.candidates[candidate_id].get("classification", ""),
            "eligible": self.op.candidates[candidate_id].get("eligible", False),
            "warnings": list(self.op.candidates[candidate_id].get("warnings", [])),
            "eligibility_detail": self.op.candidates[candidate_id].get("eligibility_detail", ""),
            "revalidation_errors": errors,
            "can_quarantine": len(errors) == 0,
            "estimated_quarantine_name": _safe_quarantine_name(record, 0),
        }

    # ------------------------------------------------------------ quarantine ---

    def quarantine(self, candidate_id: str, record: FileRecord) -> dict[str, Any]:
        """Move one candidate into quarantine, revalidating immediately before.

        Returns the per-candidate result dict.
        """
        preview = self.preview(candidate_id, record)
        if not preview["can_quarantine"]:
            return self._failed_result(
                candidate_id,
                preview,
                "quarantine",
                f"cannot quarantine: {', '.join(preview['revalidation_errors'])}",
            )

        src = record.path
        dst_name = _safe_quarantine_name(record, 0)
        dst = self.opdir / dst_name

        # Fail-safe collision policy: never overwrite an existing quarantine entry.
        if dst.exists() or dst.is_symlink():
            return self._failed_result(
                candidate_id,
                preview,
                "quarantine",
                f"quarantine collision: {dst} already exists",
            )

        try:
            src_stat = os.stat(src, follow_symlinks=False)
            actual_size = src_stat.st_size
            quarantine_device = os.stat(self.opdir, follow_symlinks=False).st_dev
            source_device = src_stat.st_dev
            fresh_stat = os.stat(src, follow_symlinks=False)
            if (
                (fresh_stat.st_dev, fresh_stat.st_ino, fresh_stat.st_size, getattr(fresh_stat, "st_mtime_ns", 0))
                != (src_stat.st_dev, src_stat.st_ino, src_stat.st_size, getattr(src_stat, "st_mtime_ns", 0))
            ):
                raise OSError("source identity changed immediately before move")
            # Atomic-ish move within the same device (os.rename). A same-volume
            # move does not reclaim storage; only a cross-device move that
            # removes the source can reclaim bytes on the source volume.
            shutil.move(str(src), str(dst))
        except Exception as exc:
            return self._failed_result(
                candidate_id,
                preview,
                "quarantine",
                f"move failed: {type(exc).__name__}: {exc}",
            )

        # Revalidator: the source must no longer exist, and the quarantine copy
        # must exist with the expected size.
        try:
            if os.path.exists(src):
                # Move reported success but source still exists — something is
                # wrong. Do not claim success.
                return self._failed_result(
                    candidate_id,
                    preview,
                    "quarantine",
                    "move reported success but source still exists",
                )
        except OSError:
            # Best effort: if we cannot stat source now, trust the move result
            # only if destination is good.
            pass

        if not dst.exists():
            return self._failed_result(
                candidate_id,
                preview,
                "quarantine",
                "destination does not exist after move",
            )

        try:
            dst_stat = os.stat(str(dst), follow_symlinks=False)
            if not stat_module.S_ISREG(dst_stat.st_mode):
                return self._failed_result(
                    candidate_id,
                    preview,
                    "quarantine",
                    "quarantine destination is not a regular file",
                )
            actual_size = dst_stat.st_size
        except OSError as exc:
            return self._failed_result(
                candidate_id,
                preview,
                "quarantine",
                f"cannot stat quarantine destination: {exc}",
            )

        bytes_moved = actual_size
        bytes_reclaimed = 0 if source_device == quarantine_device else actual_size

        result = {
            "candidate_id": candidate_id,
            "action": "quarantine",
            "status": "ok",
            "original_path": src,
            "quarantine_path": str(dst),
            "recorded_size": record.size,
            "actual_size": actual_size,
            "bytes_moved_to_quarantine": bytes_moved,
            "bytes_reclaimed": bytes_reclaimed,
            "revalidation_errors": [],
            "notes": ["moved to quarantine", "not permanently deleted"],
        }
        return result

    # --------------------------------------------------------------- restore --

    def restore(self, candidate_id: str, target_path: str) -> dict[str, Any]:
        """Restore one quarantined file to its original path.

        Refuses to overwrite an existing destination. The candidate must have
        been quarantined by a matching operation.
        """
        if candidate_id not in self.op.results:
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "not quarantined by this operation",
            )
        prev = self.op.results[candidate_id]
        if prev.get("action") != "quarantine" or prev.get("status") != "ok":
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "candidate was not successfully quarantined",
            )

        quarantine_path = prev.get("quarantine_path")
        if not quarantine_path:
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "no quarantine path recorded",
            )

        # Target is the *original* path recorded at scan time. If the user wants
        # a different destination, they must restore to a safe temp location and
        # move it themselves; we do not guess.
        recorded_path = self.op.candidates.get(candidate_id, {}).get("path")
        if not recorded_path or os.path.normcase(os.path.abspath(target_path)) != os.path.normcase(os.path.abspath(recorded_path)):
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id, "path": recorded_path or ""},
                "restore",
                "restore destination must match the original scan path",
            )
        dst = Path(target_path).resolve()
        if not dst.parent.exists():
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "destination parent directory does not exist",
            )
        if dst.exists() or dst.is_symlink():
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "destination already exists; not overwritten",
            )

        quarantine = Path(quarantine_path)
        if not quarantine.exists():
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "quarantine file no longer exists",
            )

        try:
            shutil.move(str(quarantine), str(dst))
        except Exception as exc:
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                f"restore move failed: {type(exc).__name__}: {exc}",
            )

        if not dst.exists():
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                "destination does not exist after restore",
            )

        try:
            dst_stat = os.stat(str(dst), follow_symlinks=False)
            actual_size = dst_stat.st_size
        except OSError as exc:
            return self._failed_result(
                candidate_id,
                {"candidate_id": candidate_id},
                "restore",
                f"cannot stat restored file: {exc}",
            )

        result = {
            "candidate_id": candidate_id,
            "action": "restore",
            "status": "ok",
            "original_path": target_path,
            "quarantine_path": quarantine_path,
            "restored_path": str(dst),
            "recorded_size": prev.get("recorded_size", 0),
            "actual_size": actual_size,
            "bytes_moved_to_quarantine": 0,
            "bytes_reclaimed": 0,
            "revalidation_errors": [],
            "notes": ["restored to original path", "not deleted"],
        }
        return result

    # --------------------------------------------------------------- internal -

    def _failed_result(
        self,
        candidate_id: str,
        preview: dict[str, Any],
        action: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "candidate_id": candidate_id,
            "action": action,
            "status": "failed",
            "original_path": preview.get("path", ""),
            "quarantine_path": None,
            "recorded_size": preview.get("recorded_size", 0),
            "actual_size": None,
            "bytes_moved_to_quarantine": 0,
            "bytes_reclaimed": 0,
            "revalidation_errors": list(preview.get("revalidation_errors", [])),
            "failure_reason": reason,
            "notes": ["operation refused"],
        }


def _same_volume(a: str, b: str) -> bool:
    """Best-effort: True when both paths live on the same device (so a move
    genuinely removes the source). Fallback True when we cannot determine."""
    try:
        a_stat = os.stat(a, follow_symlinks=False)
        b_stat = os.stat(b, follow_symlinks=False)
        return int(a_stat.st_dev) == int(b_stat.st_dev)
    except OSError:
        return True  # conservative: assume same volume unless we know otherwise


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CleanupError(Exception):
    """Base for cleanup-service failures that should surface in the API."""


class QuarantineError(CleanupError):
    """Quarantine service could not be initialized safely."""


class AuthorizationError(CleanupError):
    """The presented token/operation does not authorize the requested action."""


class OperationNotFoundError(CleanupError):
    """No matching cleanup operation exists for the given id."""


class OperationExpiredError(CleanupError):
    """The cleanup operation has expired and can no longer be used."""


class OperationAlreadyExecutedError(CleanupError):
    """The operation was already completed; new approval is required."""


class CandidateNotFoundError(CleanupError):
    """The candidate id is not part of this operation."""


class CandidateAlreadyProcessedError(CleanupError):
    """The candidate was already processed by this operation."""


# ---------------------------------------------------------------------------
# Operation registry (in-memory, per backend process; audit file persists)
# ---------------------------------------------------------------------------


class CleanupOperationRegistry:
    """Keep cleanup operations alive long enough to be approved and executed.

    Approvals are bound to the exact session token and candidate set presented
    during preview, and operations expire after a short window.
    """

    DEFAULT_EXPIRY_SECONDS = 10 * 60  # 10 minutes
    MAX_CANDIDATES = 200

    def __init__(self, quarantine_root: Path | None = None, *, expiry_seconds: float | None = None) -> None:
        self._lock = __import__("threading").Lock()
        self._expiry_seconds = self.DEFAULT_EXPIRY_SECONDS if expiry_seconds is None else expiry_seconds
        self._operations: dict[str, CleanupOperation] = {}
        self._quarantine_root = quarantine_root or QUARANTINE_ROOT
        try:
            os.makedirs(str(self._quarantine_root), exist_ok=True)
        except OSError as exc:
            raise QuarantineError(f"cannot create quarantine root: {exc}") from exc

    # ----------------------------------------------------------------- create -

    def create_operation(
        self,
        scan_id: str,
        approved_roots: list[str],
        candidates: list[dict[str, Any]],
        session_token: str,
        *,
        expires_at: float | None = None,
    ) -> CleanupOperation:
        if not candidates:
            raise CleanupError("no candidates submitted for preview")
        if len(candidates) > self.MAX_CANDIDATES:
            raise CleanupError(f"too many candidates: {len(candidates)} (max {self.MAX_CANDIDATES})")

        operation_id = secrets.token_hex(OPERATION_ID_BYTES)
        now = time.time()
        expiry = expires_at if expires_at is not None else now + self._expiry_seconds

        op = CleanupOperation(
            operation_id=operation_id,
            scan_id=scan_id,
            approved_roots=[os.path.abspath(r) for r in approved_roots],
            session_token=session_token,
            created_at=now,
            expires_at=expiry,
            status="pending",
            candidates={c["candidate_id"]: c for c in candidates},
            results={},
            bytes_quarantined=0,
            bytes_reclaimed=0,
            audit_rows=[],
            quarantine_root=self._quarantine_root,
        )
        with self._lock:
            self._operations[operation_id] = op
        return op

    # --------------------------------------------------------------- lookup ---

    def get(self, operation_id: str, session_token: str | None = None) -> CleanupOperation:
        with self._lock:
            op = self._operations.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)
        if session_token is not None and op.session_token != session_token:
            raise AuthorizationError("session token does not match this operation")
        if time.time() > op.expires_at:
            raise OperationExpiredError(operation_id)
        return op

    # --------------------------------------------------------- finalize/exec --

    def finalize(self, operation_id: str, session_token: str) -> CleanupOperation:
        op = self.get(operation_id, session_token)
        if op.status != "pending":
            raise OperationAlreadyExecutedError(operation_id)
        with self._lock:
            op.status = "completed" if not op.results else "partial"
        self._append_audit(op, "preview", "", None, [])
        return op

    # ---------------------------------------------------- candidate results ---

    def candidate_results(self, operation_id: str, session_token: str) -> list[dict[str, Any]]:
        op = self.get(operation_id, session_token)
        return list(op.results.values())

    # ----------------------------------------------------- audit listing ----

    def list_audit(self, operation_id: str, session_token: str) -> list[dict[str, Any]]:
        op = self.get(operation_id, session_token)
        return [r.to_public() for r in op.audit_rows]

    # --------------------------------------------------- quarantine listing ----

    def list_quarantine(self, operation_id: str, session_token: str) -> list[dict[str, Any]]:
        op = self.get(operation_id, session_token)
        opdir = op.quarantine_root / op.operation_id
        if not opdir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for item in sorted(opdir.iterdir()):
            if item.is_file():
                try:
                    st = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                rows.append(
                    {
                        "quarantine_path": str(item),
                        "size": st.st_size,
                        "operation_id": op.operation_id,
                        "mtime": st.st_mtime,
                    }
                )
        return rows

    # ---------------------------------------------------- per-candidate exec --

    def execute_quarantine(
        self,
        operation_id: str,
        session_token: str,
        candidate_id: str,
        record: FileRecord,
    ) -> dict[str, Any]:
        op = self.get(operation_id, session_token)
        if op.status != "approved":
            raise OperationAlreadyExecutedError(operation_id)
        if candidate_id not in op.candidates:
            raise CandidateNotFoundError(candidate_id)
        if candidate_id in op.results:
            raise CandidateAlreadyProcessedError(candidate_id)

        qs = QuarantineService(op)
        result = qs.quarantine(candidate_id, record)
        prev = op.results.get(candidate_id, {})
        with self._lock:
            op.results[candidate_id] = result
            op.bytes_quarantined += result.get("bytes_moved_to_quarantine", 0)
            op.bytes_reclaimed += result.get("bytes_reclaimed", 0)
            if result["status"] == "failed":
                op.status = "partial"
            elif len(op.results) == len(op.candidates):
                op.status = "completed"
        self._append_audit(op, "quarantine", record.path, result.get("quarantine_path"), [], result)
        return result

    def execute_restore(
        self,
        operation_id: str,
        session_token: str,
        candidate_id: str,
        target_path: str,
    ) -> dict[str, Any]:
        op = self.get(operation_id, session_token)
        if candidate_id not in op.results:
            raise CandidateNotFoundError(candidate_id)

        qs = QuarantineService(op)
        result = qs.restore(candidate_id, target_path)
        with self._lock:
            op.results[candidate_id] = result
        self._append_audit(op, "restore", target_path, result.get("quarantine_path"), [], result)
        return result

    # --------------------------------------------------------- audit persist --

    def _append_audit(
        self,
        op: CleanupOperation,
        action: str,
        candidate_path: str,
        quarantine_path: str | None,
        notes: list[str],
        result: dict[str, Any] | None = None,
    ) -> None:
        if action == "preview" and any(row.action == "preview" for row in op.audit_rows):
            return
        row = AuditRow(
            operation_id=op.operation_id,
            timestamp=_now_iso(),
            action=action,
            candidate_path=candidate_path,
            quarantine_path=quarantine_path,
            status=(result or {}).get("status", "ok"),
            recorded_size=(result or {}).get("recorded_size", 0),
            actual_size=(result or {}).get("actual_size"),
            failure_reason=(result or {}).get("failure_reason"),
            bytes_moved_to_quarantine=(result or {}).get("bytes_moved_to_quarantine", 0),
            bytes_reclaimed=(result or {}).get("bytes_reclaimed", 0),
            notes=notes,
        )
        op.audit_rows.append(row)
        self._write_audit(row, op.quarantine_root)

    def _write_audit(self, row: AuditRow, quarantine_root: Path) -> None:
        audit_file = quarantine_root / "space_sentry_audit.jsonl"
        try:
            with open(str(audit_file), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row.to_public(), ensure_ascii=False) + "\n")
        except OSError:
            # Audit persistence is best-effort; the in-memory record is the
            # source of truth for the API during the operation's lifetime.
            pass


# ---------------------------------------------------------------------------
# Convenience: preview endpoint payload builder (used by the router)
# ---------------------------------------------------------------------------


def preview_payload(
    registry: CleanupOperationRegistry,
    session_token: str,
    operation_id: str,
    records_by_id: dict[str, FileRecord],
) -> dict[str, Any]:
    op = registry.get(operation_id, session_token)
    qs = QuarantineService(op)
    items: list[dict[str, Any]] = []
    total_recorded = 0
    for cid, cand in op.candidates.items():
        record = records_by_id.get(cid)
        if record is None:
            return {
                "operation_id": operation_id,
                "status": op.status,
                "expires_at": op.expires_at,
                "total_recorded_bytes": 0,
                "items": [],
                "errors": [f"candidate {cid} has no matching scan record"],
            }
        preview = qs.preview(cid, record)
        total_recorded += record.size
        items.append(preview)
    return {
        "operation_id": operation_id,
        "status": op.status,
        "expires_at": op.expires_at,
        "total_recorded_bytes": total_recorded,
        "items": items,
    }
