/**
 * API types mirroring the actual backend response schemas
 * (backend/app/schemas/scan.py, backend/app/schemas/analysis.py) and the
 * scanner's summary/progress dicts produced in
 * backend/app/services/scanner.py (ScanSummary / ScanProgress.to_public()).
 * Verify against the backend before changing — no invented fields.
 */

/* ------------------------------------------------------ scanner.py shapes */

export interface ScanProgress {
  files_scanned: number;
  bytes_scanned: number;
  directories_scanned: number;
  files_skipped: number;
  current_root: string | null;
  current_path: string | null;
}

export interface ScanSummary {
  roots: string[];
  file_count: number;
  bytes_scanned: number;
  directory_count: number;
  skipped: { counts: Record<string, number>; samples: Record<string, string[]> };
  root_errors: string[];
  cancelled: boolean;
  capped_files: boolean;
}

/* ------------------------------------------------------------ scans.py */

export interface ScanStartRequest {
  roots: string[];
}

export interface ScanCreatedResponse {
  scan_id: string;
}

export interface ScanStatus {
  scan_id: string;
  status: string;
  progress: Partial<ScanProgress> | Record<string, never>;
  summary: ScanSummary | null;
  error: string | null;
}

export interface FileRecordModel {
  path: string;
  size: number;
  mtime: number;
  extension: string;
  status: string;
}

export interface DirectoryRecordModel {
  path: string;
  total_size: number;
  file_count: number;
}

export interface ScanResultsResponse {
  scan_id: string;
  status: string;
  files: FileRecordModel[];
  directories: DirectoryRecordModel[];
  truncated: boolean;
}

export interface DriveInfoModel {
  drive: string;
  drive_type: string;
  total_bytes: number;
  free_bytes: number;
}

export interface DrivesResponse {
  drives: DriveInfoModel[];
}

/* -------------------------------------------------------- analysis.py */

export interface LargeFileEntry {
  path: string;
  size: number;
  extension: string;
  mtime: number;
}

export interface LargeFilesResponse {
  scan_id: string;
  status: string;
  partial: boolean;
  total_files: number;
  eligible_count: number;
  total_eligible_bytes: number;
  files: LargeFileEntry[];
  truncated: boolean;
}

export interface DuplicateGroup {
  hash: string;
  size: number;
  paths: string[];
  copy_count: number;
}

export interface DuplicatesResponse {
  scan_id: string;
  status: string;
  partial: boolean;
  groups: DuplicateGroup[];
  excluded_counts: Record<string, number>;
  duplicate_group_count: number;
  reclaimable_if_one_copy_removed: number;
}

export interface FindingEntry {
  path: string;
  size: number;
  category: string;
  reason: string;
  review_only_hint: string | null;
}

export interface FindingsResponse {
  scan_id: string;
  status: string;
  partial: boolean;
  findings: FindingEntry[];
  category_summary: Record<string, { file_count: number; total_bytes: number }>;
  uncategorized_count: number;
  total_files: number;
}

export interface EvaluationEntry {
  path: string;
  canonical_path: string | null;
  size: number;
  category: string;
  reason: string;
  classification: string;
  warnings: string[];
  eligible: boolean;
  eligibility_detail: string;
}

export interface RecommendationsResponse {
  scan_id: string;
  status: string;
  partial: boolean;
  evaluations: EvaluationEntry[];
  counts: Record<string, number>;
  bytes: Record<string, number>;
  by_category: Record<string, Record<string, number>>;
}
