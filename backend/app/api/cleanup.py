"""Phase 4 — user-approved cleanup, quarantine, restore, and audit.

Security posture
----------------
* Candidates are bound to a completed scan and revalidated against the
  registry's file records on preview and again immediately before every
  filesystem action.
* Approvals are short-lived, single-use session tokens bound to the exact
  candidate set and metadata from the preview.
* Only candidates classified as ``potential_cleanup`` by the cleanup policy
  may be approved; ``review_required`` and ``protected`` candidates are
  rejected during preview so they can never be approved later.
* Quarantine is the default action (move to a dedicated non-system
  directory); permanent deletion is not exposed. Restore refuses to
  overwrite an existing destination.
* Every action revalidates canonical path containment, file type, reparse
  status, existence, size, and mtime_ns identity before acting.
  Changed/replaced files are refused, not operated on.
* The API remains localhost-only via the existing binding guard in main.py.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Depends, Request

from app.schemas.cleanup import (
    CleanupApproveRequest,
    CleanupCandidateResult,
    CleanupExecuteResponse,
    CleanupListResponse,
    CleanupOperationResponse,
    CleanupPreviewItem,
    CleanupPreviewRequest,
    CleanupPreviewResponse,
    CleanupQuarantineItem,
    CleanupQuarantineListResponse,
    CleanupQuarantineRequest,
    CleanupRestoreRequest,
    CleanupAuditResponse,
    CleanupAuditRow,
    CleanupOperationSummary,
)
from app.services.cleanup_executor import (
    CleanupOperationRegistry,
    AuthorizationError,
    CandidateAlreadyProcessedError,
    CandidateNotFoundError,
    CleanupError,
    OperationAlreadyExecutedError,
    OperationExpiredError,
    OperationNotFoundError,
    QuarantineError,
    preview_payload,
    make_session_token,
)
from app.services.scanner import FileRecord
from app.services.scan_registry import ScanRegistry, UnknownScanError

router = APIRouter(tags=["cleanup"])

# The cleanup API reads scan results from the ScanRegistry with which it is
# wired at import time. The intended wiring is to the scans API registry, so
# a candidate id presented here is always bound to a verified scan record.
# Tests override this with an isolated registry+scanner pair.
_wired_scan_registry: ScanRegistry | None = None


def _scan_registry_dependency(request: Request) -> ScanRegistry:
    registry = getattr(request.app.state, "scan_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Scan registry is not configured.")
    return registry

# The cleanup runtime owns its own operation state (approvals, quarantine,
# restore). It is injected through the module-global below and overridden in
# tests so each test gets an isolated registry.
_runtime_registry: CleanupOperationRegistry | None = None


def _set_runtime_registry(registry: CleanupOperationRegistry) -> None:
    """Inject the cleanup operation registry (approvals + quarantine + restore).

    Tests override this with an isolated instance so each test is hermetic.
    """
    global _runtime_registry
    _runtime_registry = registry


def _set_wired_runtime_registry(scan_registry: ScanRegistry) -> None:
    """Deprecated test hook; request app state is the authoritative source."""
    global _wired_scan_registry
    _wired_scan_registry = scan_registry

_set_wired_registry = _set_wired_runtime_registry

def _get_runtime_registry() -> CleanupOperationRegistry:
    """Return the cleanup runtime registry, creating an isolated one if needed."""
    global _runtime_registry
    if _runtime_registry is None:
        _runtime_registry = CleanupOperationRegistry()
    return _runtime_registry


def _get_scan_files(scan_registry: ScanRegistry, scan_id: str):
    """Return (scan_id, approved_roots, file_records) for a completed scan only."""
    try:
        info = scan_registry.get_analysis_input(scan_id)
    except UnknownScanError as exc:
        raise HTTPException(status_code=404, detail="Unknown scan id.") from exc

    if info["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Cleanup candidates require a completed scan (status={info['status']}).",
        )

    from app.services.scanner import FileRecord

    # Canonical candidate-id representation: every record carries a str path.
    # Paths are normalised once here so duplicate detection, candidate ids
    # and record lookups all speak the same language.
    records: list[FileRecord] = []
    for file_record in info["files"]:
        if isinstance(file_record, FileRecord):
            records.append(file_record)
            continue
        if isinstance(file_record, dict):
            values = dict(file_record)
            values["path"] = str(values.get("path", ""))
            values["mtime"] = float(values.get("mtime", 0))
            values["extension"] = str(values.get("extension", ""))
            values["mtime_ns"] = int(values.get("mtime_ns", 0))
            values["status"] = str(values.get("status", "ok"))
            records.append(FileRecord(**values))
            continue
        raise HTTPException(status_code=422, detail="Scan contains an invalid file record.")
    return info["scan_id"], info["roots"], records


def _records_by_id(records):
    return {r.path: r for r in records}


def _eligible_candidates(records, roots):
    """Return candidates that the cleanup policy marks eligible *and* that are
    currently representable by a real scan record."""
    from app.services.cleanup_policy import evaluate_findings
    from app.services.categorizer import categorize_files
    from app.services.duplicate_detector import detect_duplicates

    policy_input = {"files": records, "roots": roots}
    duplicates = detect_duplicates(records)
    categorized = categorize_files(records, duplicates, now_mtime=time.time())
    report = evaluate_findings(categorized.findings, roots)

    eligible = []
    seen_candidate_ids: set[str] = set()
    for ev in report["evaluations"]:
        if ev["eligible"] and ev["classification"] == "potential_cleanup":
            # Bind this evaluation as a candidate under its recorded path id.
            # The test submits candidate_ids as str(Path) strings, so we must
            # normalise ev["path"] to a plain str to match.
            candidate_id = ev["path"] if isinstance(ev["path"], str) else str(ev["path"])
            if candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            eligible.append(
                {
                    "candidate_id": candidate_id,
                    "path": ev["path"] if isinstance(ev["path"], str) else str(ev["path"]),
                    "canonical_path": (
                        ev["canonical_path"]
                        if ev["canonical_path"] is not None
                        else None
                    ),
                    "size": ev["size"],
                    "category": ev["category"],
                    "reason": ev["reason"],
                    "classification": ev["classification"],
                    "eligible": ev["eligible"],
                    "warnings": ev["warnings"],
                    "eligibility_detail": ev["eligibility_detail"],
                }
            )
    return eligible


# ------------------------------------------------------------------ preview ---


@router.post(
    "/cleanup/preview",
    response_model=CleanupPreviewResponse,
    status_code=201,
)
def cleanup_preview(
    request: CleanupPreviewRequest,
    scan_registry: ScanRegistry = Depends(_scan_registry_dependency),
):
    """Preview a cleanup batch for a completed scan.

    Returns per-candidate preview items with exact paths, sizes, reasons,
    warnings, revalidation errors, and a short-lived session token binding the
    candidate set. No file is modified during preview.
    """
    # Check scan lifecycle before loading/validating candidates, so a running
    # scan consistently returns 409 rather than an eligibility 422.
    try:
        snapshot = scan_registry.get_snapshot(request.scan_id)
    except UnknownScanError as exc:
        raise HTTPException(status_code=404, detail="Unknown scan id.") from exc
    if snapshot["status"] != "completed":
        raise HTTPException(status_code=409, detail=f"Scan is not completed (status={snapshot['status']}).")
    scan_id, roots, records = _get_scan_files(scan_registry, request.scan_id)
    records_by_id = _records_by_id(records)

    # Only eligible potential_cleanup candidates may be previewed for cleanup.
    requested_ids = set(request.candidate_ids)
    eligible = _eligible_candidates(records, roots)

    if not eligible:
        raise HTTPException(status_code=422, detail="No eligible cleanup candidates were found for this scan.")

    # Build candidate set bound to this batch.
    # Every requested candidate must resolve to a real scan record and pass
    # the cleanup policy before it is bound into this batch.
    selected = []
    for c in eligible:
        if c["candidate_id"] not in requested_ids:
            continue
        record = records_by_id.get(c["path"])
        if record is None:
            continue
        selected.append(
            {
                "candidate_id": c["candidate_id"],
                "path": c["path"],
                "canonical": c["canonical_path"],
                "size": c["size"],
                "mtime_ns": record.mtime_ns,
                "extension": record.extension,
                "category": c["category"],
                "reason": c["reason"],
                "classification": c["classification"],
                "eligible": c["eligible"],
                "warnings": list(c["warnings"]),
                "eligibility_detail": c["eligibility_detail"],
            }
        )
    if len(selected) != len(requested_ids):
        unknown = sorted(requested_ids - {c["candidate_id"] for c in selected})
        raise HTTPException(
            status_code=422,
            detail=f"Candidates not eligible or not found: {', '.join(unknown[:200])}",
        )

    token = make_session_token()
    op = _runtime_registry.create_operation(
        scan_id=scan_id,
        approved_roots=roots,
        candidates=selected,
        session_token=token,
    )

    payload = preview_payload(_runtime_registry, op.session_token, op.operation_id, records_by_id)
    errors = payload.get("errors", [])
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    _runtime_registry._append_audit(op, "preview", "", None, [])
    return CleanupPreviewResponse(
        operation_id=payload["operation_id"],
        status=op.status,
        expires_at=op.expires_at,
        total_recorded_bytes=payload["total_recorded_bytes"],
        items=[CleanupPreviewItem(**item) for item in payload["items"]],
        errors=[],
        session_token=op.session_token,
    )


@router.post(
    "/cleanup/approve",
    response_model=CleanupOperationResponse,
    status_code=201,
)
def cleanup_approve(request: CleanupApproveRequest):
    """Explicitly approve a previously-previewed cleanup batch.

    Returns the operation summary. Approval does not move any file; it only
    marks the operation as approved and ready for per-candidate quarantine
    execution.
    """
    try:
        op = _runtime_registry.get(request.operation_id, request.session_token)
    except OperationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OperationExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if op.status != "pending":
        raise HTTPException(status_code=409, detail="Operation already approved or executed.")
    with _runtime_registry._lock:
        op.status = "approved"
    _runtime_registry._append_audit(op, "approve", "", None, [])

    return CleanupOperationResponse(
        operation_id=op.operation_id,
        scan_id=op.scan_id,
        status=op.status,
        created_at=op.created_at,
        expires_at=op.expires_at,
        bytes_quarantined=op.bytes_quarantined,
        bytes_reclaimed=op.bytes_reclaimed,
        candidates=list(op.candidates.values()),
        results=list(op.results.values()),
    )


# --------------------------------------------------------------- per-candidate exec ---


@router.post("/cleanup/quarantine", response_model=CleanupExecuteResponse)
def cleanup_quarantine(
    request: CleanupQuarantineRequest,
    scan_registry: ScanRegistry = Depends(_scan_registry_dependency),
):
    """Quarantine one approved candidate.

    Revalidates the candidate immediately before moving it. Rejects if the
    candidate is outside approved roots, is a symlink/reparse point/directory,
    has changed since the scan, or if quarantine would collide with an existing
    file.
    """
    try:
        op = _runtime_registry.get(request.operation_id, request.session_token)
    except (OperationNotFoundError, OperationExpiredError, AuthorizationError) as exc:
        raise HTTPException(
            status_code=403 if isinstance(exc, AuthorizationError) else 404,
            detail=str(exc),
        ) from exc

    if request.candidate_id in op.results:
        raise HTTPException(status_code=409, detail=f"already processed: {request.candidate_id}")
    if op.status != "approved":
        raise HTTPException(status_code=409, detail="Operation must be approved before per-candidate quarantine execution.")

    scan_id, roots, records = _get_scan_files(scan_registry, op.scan_id)
    records_by_id = _records_by_id(records)

    cand = op.candidates.get(request.candidate_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="Candidate not part of this operation.")

    record = records_by_id.get(cand["path"])
    if record is None:
        raise HTTPException(status_code=422, detail="Candidate has no matching scan record at execution time.")

    try:
        result = _runtime_registry.execute_quarantine(
            request.operation_id,
            op.session_token,
            request.candidate_id,
            record,
        )
    except CandidateAlreadyProcessedError as exc:
        raise HTTPException(status_code=409, detail=f"already processed: {request.candidate_id}") from exc
    except OperationAlreadyExecutedError as exc:
        raise HTTPException(status_code=409, detail="Operation already executed.") from exc
    except CleanupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CleanupExecuteResponse(
        operation_id=request.operation_id,
        candidate_id=request.candidate_id,
        result=CleanupCandidateResult(**result),
    )


@router.post("/cleanup/restore", response_model=CleanupExecuteResponse)
def cleanup_restore(request: CleanupRestoreRequest):
    """Restore a quarantined file to its original path.

    Refuses to overwrite an existing destination file.
    """
    try:
        op = _runtime_registry.get(request.operation_id, request.session_token)
    except (OperationNotFoundError, OperationExpiredError, AuthorizationError) as exc:
        raise HTTPException(
            status_code=403 if isinstance(exc, AuthorizationError) else 404,
            detail=str(exc),
        ) from exc

    try:
        result = _runtime_registry.execute_restore(
            request.operation_id,
            op.session_token,
            request.candidate_id,
            request.target_path,
        )
    except (CandidateNotFoundError, OperationAlreadyExecutedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CleanupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CleanupExecuteResponse(
        operation_id=request.operation_id,
        candidate_id=request.candidate_id,
        result=CleanupCandidateResult(**result),
    )


# --------------------------------------------------------------- listing ---------


@router.get("/cleanup/operations", response_model=CleanupListResponse)
def cleanup_list_operations():
    """List active cleanup operations (non-expired ones are visible)."""
    with _runtime_registry._lock:
        ops = list(_runtime_registry._operations.values())
    ops = [op for op in ops if time.time() <= op.expires_at]
    summaries = []
    for op in ops:
        results = list(op.results.values())
        succeeded = sum(1 for r in results if r["status"] == "ok")
        failed = sum(1 for r in results if r["status"] == "failed")
        summaries.append(
            CleanupOperationSummary(
                operation_id=op.operation_id,
                scan_id=op.scan_id,
                status=op.status,
                created_at=op.created_at,
                expires_at=op.expires_at,
                bytes_quarantined=op.bytes_quarantined,
                bytes_reclaimed=op.bytes_reclaimed,
                candidate_count=len(op.candidates),
                succeeded_count=succeeded,
                failed_count=failed,
            )
        )
    return CleanupListResponse(operations=summaries)


@router.get("/cleanup/operations/{operation_id}", response_model=CleanupOperationResponse)
def cleanup_get_operation(operation_id: str, session_token: str = Query(..., description="Session token")):
    """Get an operation's full candidate/result state."""
    try:
        op = _runtime_registry.get(operation_id, session_token)
    except (OperationNotFoundError, OperationExpiredError, AuthorizationError) as exc:
        raise HTTPException(
            status_code=403 if isinstance(exc, AuthorizationError) else 404,
            detail=str(exc),
        ) from exc
    return CleanupOperationResponse(
        operation_id=op.operation_id,
        scan_id=op.scan_id,
        status=op.status,
        created_at=op.created_at,
        expires_at=op.expires_at,
        bytes_quarantined=op.bytes_quarantined,
        bytes_reclaimed=op.bytes_reclaimed,
        candidates=list(op.candidates.values()),
        results=[CleanupCandidateResult(**r) for r in op.results.values()],
    )


@router.get(
    "/cleanup/operations/{operation_id}/quarantine",
    response_model=CleanupQuarantineListResponse,
)
def cleanup_list_quarantine(operation_id: str, session_token: str = Query(..., description="Session token")):
    """List files quarantined by a specific operation."""
    try:
        op = _runtime_registry.get(operation_id, session_token)
    except (OperationNotFoundError, OperationExpiredError, AuthorizationError) as exc:
        raise HTTPException(
            status_code=403 if isinstance(exc, AuthorizationError) else 404,
            detail=str(exc),
        ) from exc
    items = []
    opdir = op.quarantine_root / op.operation_id
    if opdir.exists():
        for item in sorted(opdir.iterdir()):
            if item.is_file():
                try:
                    st = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                items.append(
                    CleanupQuarantineItem(
                        quarantine_path=str(item),
                        size=st.st_size,
                        operation_id=op.operation_id,
                        mtime=st.st_mtime,
                    )
                )
    return CleanupQuarantineListResponse(operation_id=operation_id, items=items)


@router.get(
    "/cleanup/operations/{operation_id}/audit",
    response_model=CleanupAuditResponse,
)
def cleanup_list_audit(operation_id: str, session_token: str = Query(..., description="Session token")):
    """Return this operation's audit rows (timestamps, paths, statuses, bytes)."""
    try:
        op = _runtime_registry.get(operation_id, session_token)
    except (OperationNotFoundError, OperationExpiredError, AuthorizationError) as exc:
        raise HTTPException(
            status_code=403 if isinstance(exc, AuthorizationError) else 404,
            detail=str(exc),
        ) from exc
    rows = []
    for audit in op.audit_rows:
        rows.append(CleanupAuditRow(**audit.to_public()))
    return CleanupAuditResponse(operation_id=operation_id, rows=rows)
