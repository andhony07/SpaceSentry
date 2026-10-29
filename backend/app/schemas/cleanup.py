"""Typed request/response schemas for the Phase 4 cleanup API.

Everything here is derived from the existing scan registry and
cleanup_executor. There is no arbitrary-path submission: candidates must be
identifiers that the backend already associates with a verified scan record.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# --------------------------------------------------------------- requests ------

class CleanupPreviewRequest(BaseModel):
    """Bind a preview to a specific completed scan and a set of candidate ids.

    Candidate ids must be identifiers the backend already associates with that
    scan's file records; arbitrary paths are not accepted as candidates here.
    """
    scan_id: str = Field(..., description="Completed scan that produced the candidates")
    candidate_ids: list[str] = Field(min_length=1, max_length=200, description="Candidate identifiers to preview")


class CleanupApproveRequest(BaseModel):
    """Explicit user approval for a previously-previewed cleanup batch.

    The session token returned by preview is required and is bound to the
    exact candidate set metadata from that preview.
    """
    operation_id: str = Field(..., description="Operation id from the preview response")
    session_token: str = Field(..., description="Session token from the preview response")


class CleanupQuarantineRequest(BaseModel):
    operation_id: str = Field(..., description="Operation identifier")
    session_token: str = Field(..., description="Session token from preview")
    candidate_id: str = Field(..., description="Candidate identifier to quarantine")


class CleanupRestoreRequest(BaseModel):
    operation_id: str = Field(..., description="Operation that quarantined the candidate")
    session_token: str = Field(..., description="Authorization token from the preview")
    candidate_id: str = Field(..., description="Quarantined candidate to restore")
    target_path: str = Field(..., description="Original path to restore to (must be empty)")


# --------------------------------------------------------------- responses ------

class CleanupPreviewItem(BaseModel):
    candidate_id: str
    path: str
    canonical_path: str | None
    recorded_size: int
    recorded_mtime_ns: int
    category: str
    reason: str
    classification: str
    eligible: bool
    warnings: list[str] = Field(default_factory=list)
    eligibility_detail: str
    revalidation_errors: list[str] = Field(default_factory=list)
    can_quarantine: bool
    estimated_quarantine_name: str


class CleanupPreviewResponse(BaseModel):
    operation_id: str
    status: str
    expires_at: float
    total_recorded_bytes: int
    items: list[CleanupPreviewItem]
    errors: list[str] = Field(default_factory=list)
    session_token: str


class CleanupCandidateResult(BaseModel):
    candidate_id: str
    action: str
    status: str
    original_path: str
    quarantine_path: str | None = None
    restored_path: str | None = None
    recorded_size: int
    actual_size: int | None = None
    bytes_moved_to_quarantine: int = 0
    bytes_reclaimed: int = 0
    revalidation_errors: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class CleanupExecuteResponse(BaseModel):
    operation_id: str
    candidate_id: str
    result: CleanupCandidateResult


class CleanupOperationSummary(BaseModel):
    operation_id: str
    scan_id: str
    status: str
    created_at: float
    expires_at: float
    bytes_quarantined: int
    bytes_reclaimed: int
    candidate_count: int
    succeeded_count: int
    failed_count: int


class CleanupAuditRow(BaseModel):
    operation_id: str
    timestamp: str
    action: str
    candidate_path: str
    quarantine_path: str | None
    status: str
    recorded_size: int
    actual_size: int | None
    failure_reason: str | None
    bytes_moved_to_quarantine: int
    bytes_reclaimed: int
    notes: list[str] = Field(default_factory=list)


class CleanupListResponse(BaseModel):
    operations: list[CleanupOperationSummary]


class CleanupOperationResponse(BaseModel):
    operation_id: str
    scan_id: str
    status: str
    created_at: float
    expires_at: float
    bytes_quarantined: int
    bytes_reclaimed: int
    candidates: list[dict]
    results: list[CleanupCandidateResult]


class CleanupQuarantineItem(BaseModel):
    quarantine_path: str
    size: int
    operation_id: str
    mtime: float


class CleanupQuarantineListResponse(BaseModel):
    operation_id: str
    items: list[CleanupQuarantineItem]


class CleanupAuditResponse(BaseModel):
    operation_id: str
    rows: list[CleanupAuditRow]


class CleanupErrorResponse(BaseModel):
    detail: str
