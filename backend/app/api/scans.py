"""Scan API endpoints: start, poll status, fetch results, cancel."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.scan import (
    ScanCancelResponse,
    ScanCreatedResponse,
    ScanListResponse,
    ScanResultsResponse,
    ScanStartRequest,
    ScanStatusResponse,
)
from app.services.scan_registry import UnknownScanError, ScanRegistry

router = APIRouter(tags=["scans"])
registry = ScanRegistry()


@router.post("/scans", response_model=ScanCreatedResponse, status_code=201)
def start_scan(request: ScanStartRequest) -> ScanCreatedResponse:
    try:
        scan_id = registry.start_scan(request.roots)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScanCreatedResponse(scan_id=scan_id)


@router.get("/scans", response_model=ScanListResponse)
def list_scans() -> ScanListResponse:
    return ScanListResponse(scans=[ScanStatusResponse(**s) for s in registry.list_snapshots()])


@router.get("/scans/{scan_id}", response_model=ScanStatusResponse)
def get_scan(scan_id: str) -> ScanStatusResponse:
    try:
        snapshot = registry.get_snapshot(scan_id)
    except UnknownScanError as exc:
        raise HTTPException(status_code=404, detail="Unknown scan id.") from exc
    return ScanStatusResponse(
        scan_id=snapshot["scan_id"],
        status=snapshot["status"],
        progress=snapshot["progress"],
        summary=snapshot["summary"],
        error=snapshot["error"],
    )


@router.get("/scans/{scan_id}/results", response_model=ScanResultsResponse)
def get_results(scan_id: str, limit: int = Query(default=500, ge=1, le=200_000)) -> ScanResultsResponse:
    try:
        snapshot = registry.get_snapshot(scan_id)
        results = registry.take_results(scan_id, limit=limit)
    except UnknownScanError as exc:
        raise HTTPException(status_code=404, detail="Unknown scan id.") from exc
    return ScanResultsResponse(
        scan_id=scan_id,
        status=snapshot["status"],
        files=results["files"],
        directories=results["directories"],
        truncated=results["truncated"],
    )


@router.post("/scans/{scan_id}/cancel", response_model=ScanCancelResponse)
def cancel_scan(scan_id: str) -> ScanCancelResponse:
    try:
        status = registry.request_cancel(scan_id)
    except UnknownScanError as exc:
        raise HTTPException(status_code=404, detail="Unknown scan id.") from exc
    return ScanCancelResponse(scan_id=scan_id, status=status)
