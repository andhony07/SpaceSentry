"""Deterministic storage categorization (Phase 2, read-only).

Every rule here is explicit and documented in docs/categorization-rules.md.
A file can carry multiple findings. NOTHING in this module implies that a
large, old, or cache-looking file is automatically safe to remove: safety
labeling happens in cleanup_policy.py and stays conservative.

Core principles:
- Only documented rule matches create findings.
- An unmatched file is "uncategorized" and explicitly review-only.
- Ambiguous location names (bin/, obj/, dist/, build/, tmp/ at the top of a
  unknown tree) are classified review_required, never potential_cleanup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from app.services.scanner import FileRecord

# --- documented rule tables ----------------------------------------------

# Extensions that are strong signals of incomplete/scratch temporary data.
# Deliberately small: generic extensions like .log/.exe/.zip must NOT be
# treated as safe-to-delete signals anywhere in this module.
TEMPORARY_EXTENSIONS = {".tmp", ".temp", ".crdownload", ".partial"}

# Unambiguous, tool-owned cache/build directories whose default contents are
# regenerable artifacts (still require user confirmation before cleanup).
UNAMBIGUOUS_BUILD_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".vite",
    ".parcel-cache",
    ".turbo",
}

# Ambiguous names that look like build outputs but are also common names for
# hand-authored content (review only, never auto-classified as cleanup).
AMBIGUOUS_BUILD_DIRS = {"node_modules", "build", "dist", "obj", "bin", "out", "target"}

# Compiled/intermediate artifacts by extension.
ARTIFACT_EXTENSIONS = {".pyc", ".pyo", ".class", ".obj", ".o"}

# Old-file review threshold default (days).
DEFAULT_OLD_DAYS = 365

# Large-file default threshold (bytes): 100 MiB, i.e. big enough to matter.
DEFAULT_LARGE_BYTES = 100 * 1024 * 1024

# --- categories ------------------------------------------------------------

CATEGORY_TEMPORARY = "temporary_file"
CATEGORY_BUILD_CACHE = "dev_build_cache"
CATEGORY_LARGE_FILE = "large_file"
CATEGORY_OLD_FILE = "old_file"
CATEGORY_DUPLICATE = "potential_duplicate"
CATEGORY_UNCATEGORIZED = "uncategorized"


@dataclass
class Finding:
    path: str
    size: int
    category: str
    reason: str
    review_only_hint: str | None = None

    def to_public(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "category": self.category,
            "reason": self.reason,
            "review_only_hint": self.review_only_hint,
        }


@dataclass
class CategorySummaryEntry:
    category: str
    file_count: int
    total_bytes: int


@dataclass
class CategorizationReport:
    findings: list[Finding] = field(default_factory=list)
    categories: dict[str, list[Finding]] = field(default_factory=dict)
    uncategorized_count: int = 0

    def to_public(self) -> dict:
        category_summary = {}
        for category, entries in self.categories.items():
            category_summary[category] = {
                "file_count": len(entries),
                "total_bytes": sum(f.size for f in entries),
            }
        return {
            "findings": [f.to_public() for f in self.findings],
            "category_summary": category_summary,
            "uncategorized_count": self.uncategorized_count,
            "total_files": self.total_files,
        }

    total_files: int = 0


def categorize_files(
    files: list[FileRecord],
    duplicates: dict,
    *,
    now_mtime: float,
    old_days: int = DEFAULT_OLD_DAYS,
    large_threshold_bytes: int = DEFAULT_LARGE_BYTES,
) -> CategorizationReport:
    """Produce deterministic, rule-based findings for scanned files.

    ``duplicates`` is the dict returned by duplicate_detector.detect_duplicates().
    """
    if old_days < 0 or large_threshold_bytes < 0:
        raise ValueError("thresholds cannot be negative")

    report = CategorizationReport(total_files=len(files))
    duplicate_paths = {
        path for group in duplicates.get("groups", []) for path in group["paths"]
    }
    old_cutoff = now_mtime - old_days * 86400

    def add(record: FileRecord, category: str, reason: str, hint: str | None = None) -> None:
        finding = Finding(
            path=record.path,
            size=record.size,
            category=category,
            reason=reason,
            review_only_hint=hint,
        )
        report.findings.append(finding)
        report.categories.setdefault(category, []).append(finding)

    for record in files:
        matched = False
        extension = record.extension

        # Rule T1 — temporary extensions, anywhere inside the scan root.
        if extension in TEMPORARY_EXTENSIONS:
            add(
                record,
                CATEGORY_TEMPORARY,
                f"temporary-style extension '{extension}'",
                hint="Confirm the owning application no longer needs it before cleanup.",
            )
            matched = True

        # Rule B1/B2 — build artifacts and cache locations.
        directory = os.path.dirname(record.path).lower()
        segments = {seg.lower() for seg in directory.replace("/", os.sep).split(os.sep) if seg}
        if segments & UNAMBIGUOUS_BUILD_DIRS:
            add(
                record,
                CATEGORY_BUILD_CACHE,
                "inside an unambiguous tool-owned cache directory",
                hint="Still regenerable by the owning tool; confirm before cleanup.",
            )
            matched = True
        elif segments & AMBIGUOUS_BUILD_DIRS:
            add(
                record,
                CATEGORY_BUILD_CACHE,
                "inside an ambiguous build-output directory name",
                hint="Review only: 'build', 'dist', 'bin', 'obj' often hold hand-authored content.",
            )
            matched = True
        elif extension in ARTIFACT_EXTENSIONS:
            add(
                record,
                CATEGORY_BUILD_CACHE,
                f"compiled/intermediate artifact extension '{extension}'",
                hint="Regenerable in principle; verify the source project still exists.",
            )
            matched = True

        # Rule D1 — duplicates verified by content hash (never by name/size).
        if record.path in duplicate_paths:
            add(
                record,
                CATEGORY_DUPLICATE,
                "SHA-256 content matches another scanned file",
                hint="Keep at least one copy; choose which copy to remove.",
            )
            matched = True

        # Rule L1 — large files. Size alone is NEVER a cleanup signal.
        if record.size >= large_threshold_bytes:
            add(
                record,
                CATEGORY_LARGE_FILE,
                f"size {record.size} bytes >= large-file threshold",
                hint="Review only: large files are often important documents or media.",
            )
            matched = True

        # Rule O1 — old files. Age alone is NEVER a cleanup signal.
        if record.mtime <= old_cutoff:
            add(
                record,
                CATEGORY_OLD_FILE,
                f"not modified for at least {old_days} days",
                hint="Review only: age does not imply a file is deletable.",
            )
            matched = True

        if not matched:
            report.uncategorized_count += 1
            add(record, CATEGORY_UNCATEGORIZED, "no documented rule matched", hint="Review only.")

    return report
