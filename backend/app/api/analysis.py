"""Read-only analysis endpoints (Phase 2).

All routes operate on an EXISTING scan id from the Phase 1 registry and its
stored file records. There is deliberately no "analyze arbitrary path"
endpoint: analysis must be tied to a validated, user-approved scan root.

No endpoint here deletes, moves, or modifies anything on disk. Duplicate
hashing reads file contents only.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from app.schemas.analysis import (
    DuplicatesResponse,
    FindingsResponse,
    LargeFilesResponse,
    RecommendationsResponse,
)
from app.services.cleanup_policy import evaluate_findings
from app.services.duplicate_detector import DEFAULT_HASH_BUDGET_BYTES, detect_duplicates
from app.services.large_file_analyzer import analyze_large_files
from app.services.categorizer import (
    DEFAULT_LARGE_BYTES,
    DEFAULT_OLD_DAYS,
    categorize_files,
)
from app.services.scan_registry import STATUS_CANCELLED, UnknownScanError
from app.services.scanner import FileRecord

router = APIRouter(tags=["analysis"])

_ANALYSIS_ELIGIBLE_STATUSES = {"completed", "cancelled"}


def _analysis_input(registry, scan_id: str) -> dict:
    try:
        info = registry.get_analysis_input(scan_id)
    except UnknownScanError as exc:
        raise HTTPException(status_code=404, detail="Unknown scan id.") from exc
    if info["status"] not in _ANALYSIS_ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Analysis is available only for finished scans (status={info['status']}).",
        )
    # API boundary normalizes serialized records from test/imported scan data;
    # the live registry already returns FileRecord instances.
    info["files"] = [FileRecord(**record) if isinstance(record, dict) else record for record in info["files"]]
    return info


@router.get("/scans/{scan_id}/analysis/large-files", response_model=LargeFilesResponse)
def large_files(
    scan_id: str,
    min_size_bytes: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
) -> LargeFilesResponse:
    from app.api.scans import registry  # local import avoids circular module init

    info = _analysis_input(registry, scan_id)
    try:
        report = analyze_large_files(info["files"], min_size_bytes=min_size_bytes, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LargeFilesResponse(
        scan_id=scan_id,
        status=info["status"],
        partial=info["status"] == "cancelled",
        **report,
    )


@router.get("/scans/{scan_id}/analysis/duplicates", response_model=DuplicatesResponse)
def duplicates(
    scan_id: str,
    hash_budget_bytes: int = Query(default=DEFAULT_HASH_BUDGET_BYTES, ge=0, le=100 * DEFAULT_HASH_BUDGET_BYTES),
) -> DuplicatesResponse:
    from app.api.scans import registry

    info = _analysis_input(registry, scan_id)
    report = detect_duplicates(info["files"], hash_budget_bytes=hash_budget_bytes)
    return DuplicatesResponse(
        scan_id=scan_id,
        status=info["status"],
        partial=info["status"] == "cancelled",
        **report,
    )


@router.get("/scans/{scan_id}/analysis/findings", response_model=FindingsResponse)
def findings(
    scan_id: str,
    old_days: int = Query(default=DEFAULT_OLD_DAYS, ge=0, le=10_000),
    large_threshold_bytes: int = Query(default=DEFAULT_LARGE_BYTES, ge=0),
) -> FindingsResponse:
    from app.api.scans import registry

    info = _analysis_input(registry, scan_id)
    duplicates_report = detect_duplicates(info["files"], hash_budget_bytes=DEFAULT_HASH_BUDGET_BYTES)
    report = categorize_files(
        info["files"],
        duplicates_report,
        now_mtime=time.time(),
        old_days=old_days,
        large_threshold_bytes=large_threshold_bytes,
    )
    return FindingsResponse(
        scan_id=scan_id,
        status=info["status"],
        partial=info["status"] == "cancelled",
        **report.to_public(),
    )


@router.get("/scans/{scan_id}/analysis/recommendations", response_model=RecommendationsResponse)
def recommendations(
    scan_id: str,
    old_days: int = Query(default=DEFAULT_OLD_DAYS, ge=0, le=10_000),
    large_threshold_bytes: int = Query(default=DEFAULT_LARGE_BYTES, ge=0),
) -> RecommendationsResponse:
    from app.api.scans import registry

    info = _analysis_input(registry, scan_id)
    duplicates_report = detect_duplicates(info["files"], hash_budget_bytes=DEFAULT_HASH_BUDGET_BYTES)
    categorization = categorize_files(
        info["files"],
        duplicates_report,
        now_mtime=time.time(),
        old_days=old_days,
        large_threshold_bytes=large_threshold_bytes,
    )
    policy_report = evaluate_findings(categorization.findings, info["roots"])
    return RecommendationsResponse(
        scan_id=scan_id,
        status=info["status"],
        partial=info["status"] == "cancelled",
        **policy_report,
    )
