"""Typed schemas for the Phase 2 analysis API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LargeFilesResponse(BaseModel):
    scan_id: str
    status: str
    partial: bool
    total_files: int
    eligible_count: int
    total_eligible_bytes: int
    files: list[dict]
    truncated: bool


class DuplicatesResponse(BaseModel):
    scan_id: str
    status: str
    partial: bool
    groups: list[dict]
    excluded_counts: dict[str, int]
    duplicate_group_count: int
    reclaimable_if_one_copy_removed: int


class FindingsResponse(BaseModel):
    scan_id: str
    status: str
    partial: bool
    findings: list[dict]
    category_summary: dict[str, dict]
    uncategorized_count: int
    total_files: int


class RecommendationsResponse(BaseModel):
    scan_id: str
    status: str
    partial: bool
    evaluations: list[dict]
    counts: dict
    bytes: dict
    by_category: dict


class AnalysisErrorResponse(BaseModel):
    detail: str


class AnalyzeParams(BaseModel):
    """Documentation-only model for query parameter shapes."""
    min_size_bytes: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=1000)
    old_days: int = Field(default=365, ge=0)
    large_threshold_bytes: int = Field(default=100 * 1024 * 1024, ge=0)
    hash_budget_bytes: int = Field(default=1_000_000_000, ge=0)
