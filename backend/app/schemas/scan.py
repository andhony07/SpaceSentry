"""Typed request/response schemas for the scan API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScanStartRequest(BaseModel):
    roots: list[str] = Field(min_length=1, max_length=8, description="Absolute directory paths to scan")


class ScanCreatedResponse(BaseModel):
    scan_id: str


class ScanStatusResponse(BaseModel):
    scan_id: str
    status: str
    progress: dict
    summary: dict | None = None
    error: str | None = None


class FileRecordModel(BaseModel):
    path: str
    size: int
    mtime: float
    extension: str
    status: str


class DirectoryRecordModel(BaseModel):
    path: str
    total_size: int
    file_count: int


class ScanResultsResponse(BaseModel):
    scan_id: str
    status: str
    files: list[FileRecordModel]
    directories: list[DirectoryRecordModel]
    truncated: bool


class ScanListResponse(BaseModel):
    scans: list[ScanStatusResponse]


class ScanCancelResponse(BaseModel):
    scan_id: str
    status: str


class DriveInfoModel(BaseModel):
    drive: str
    drive_type: str
    total_bytes: int
    free_bytes: int


class DrivesResponse(BaseModel):
    drives: list[DriveInfoModel]


class ErrorResponse(BaseModel):
    detail: str
