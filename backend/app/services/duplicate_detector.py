"""Staged SHA-256 duplicate detection over scan results (read-only).

Pipeline (documented in docs/categorization-rules.md):
1. Stage 1 — group scan-recorded files by exact byte size; ignore small groups.
2. Stage 2 — for each candidate group (largest first), revalidate every
   file's identity against its scan-time record (size + mtime_ns + reparse
   attributes), then hash the file in bounded chunks.
3. Revalidate again after hashing; a file whose metadata changed mid-hash is
   excluded because its hash cannot be trusted.
4. A duplicate group is reported only when full SHA-256 contents match.

Safety properties:
- Files are opened for reading only. Never written, moved, renamed, deleted.
- Symlinks/reparse points are never followed for hashing.
- Large files are streamed in fixed-size chunks (no full in-memory load).
- Identical filenames are irrelevant to the decision; sizes are only a
  cheap pre-filter, never proof of duplication.
- A hashing budget bounds total bytes hashed per analysis run.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from app.services.scanner import FileRecord

HASH_CHUNK_SIZE = 65536
DEFAULT_HASH_BUDGET_BYTES = 1_000_000_000  # 1 GiB per analysis run


@dataclass
class DuplicateGroup:
    hash: str
    size: int
    paths: list[str]

    def to_public(self) -> dict:
        return {"hash": self.hash, "size": self.size, "paths": list(self.paths), "copy_count": len(self.paths)}


@dataclass
class _HashOutcome:
    path: str
    size: int
    digest: str | None
    reason: str  # "hashed" | changed_since_scan | changed_during_hash | unreadable | reparse_point | disappeared | budget_exceeded


def _as_str_path(path: object) -> str:
    """Coerce a FileRecord, Path-like, or str to a plain str path."""
    if isinstance(path, FileRecord):
        return str(getattr(path, "path", path))
    if hasattr(path, "path"):
        return str(path.path)
    return str(path)


def _meta_matches_record(record: FileRecord, st) -> bool:
    if st.st_size != record.size:
        return False
    if record.mtime_ns:
        return int(getattr(st, "st_mtime_ns", 0)) == record.mtime_ns
    # Fallback for records without ns precision (1 ms tolerance).
    return abs(getattr(st, "st_mtime", 0.0) - record.mtime) < 0.001


class _SwapDetected(Exception):
    """The file at a record path no longer has the identity the scan (or the
    pre-open stat) vouched for. Its content must never be hashed."""


def _hash_file(path: str, expected_identity: tuple[int, int], chunk_size: int = HASH_CHUNK_SIZE) -> str | None:
    """Stream SHA-256 through a GUARDED open.

    TOCTOU hardening: ``open()`` follows symlinks, so between the caller's
    pre-open stat and this open the path could be swapped to a reparse point
    or a different inode, and the digest would then describe content that the
    recorded path does not actually contain. Mitigations (both always on when
    the platform supports them):
    - O_NOFOLLOW rejects a final-component symlink at open time,
    - fstat on the OPEN HANDLE verifies the (st_dev, st_ino) identity matches
      the caller's stat, catching swaps on platforms without O_NOFOLLOW.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError:
        raise
    try:
        opened_st = os.fstat(fd)
        if (opened_st.st_dev, opened_st.st_ino) != expected_identity:
            raise _SwapDetected(path)
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=True) as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except _SwapDetected:
        raise
    return digest.hexdigest()


def _hash_and_guard(record: FileRecord, legacy_record: FileRecord | None = None) -> _HashOutcome:
    # legacy_record supports the pre-Phase-2 private test helper call shape
    # (path, record); production detection always supplies one FileRecord.
    if legacy_record is not None:
        record = legacy_record
    path = _as_str_path(record)
    try:
        st_before = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return _HashOutcome(path, record.size, None, "disappeared")
    except OSError:
        return _HashOutcome(path, record.size, None, "unreadable")

    if getattr(st_before, "st_file_attributes", 0) & 0x400:
        return _HashOutcome(path, record.size, None, "reparse_point")
    if not _meta_matches_record(record, st_before):
        return _HashOutcome(path, st_before.st_size, None, "changed_since_scan")

    try:
        digest = _hash_file(path, (st_before.st_dev, st_before.st_ino))
    except _SwapDetected:
        return _HashOutcome(path, record.size, None, "swapped_during_open")
    except (FileNotFoundError, NotADirectoryError):
        return _HashOutcome(path, record.size, None, "disappeared")
    except OSError:
        return _HashOutcome(path, record.size, None, "unreadable")

    try:
        st_after = os.stat(path, follow_symlinks=False)
    except OSError:
        return _HashOutcome(path, record.size, None, "unreadable")
    if not _meta_matches_record(record, st_after):
        return _HashOutcome(path, st_after.st_size, None, "changed_during_hash")

    return _HashOutcome(path, record.size, digest, "hashed")


def detect_duplicates(
    files: list[FileRecord],
    *,
    hash_budget_bytes: int = DEFAULT_HASH_BUDGET_BYTES,
) -> dict:
    """Report groups of files with identical SHA-256 content.

    Files are never automatically deleted or otherwise altered; the caller
    (and later, the user) decides what to do with a group.
    """
    if hash_budget_bytes < 0:
        raise ValueError("hash_budget_bytes cannot be negative")

    # Stage 1: size grouping. Includes size 0 (repeated empty files); only a
    # pre-filter — never proof of duplication.
    # Sort by a deterministic, case-insensitive key.  ``f`` may be a FileRecord
    # or a Path-like object (as produced by the tests' in-memory scan helper).
    # Extract the underlying path string before calling .lower().
    def _sort_key(f: object) -> str:
        return _as_str_path(f).lower()

    by_size: dict[int, list[FileRecord]] = {}
    for record in sorted(files, key=_sort_key):
        by_size.setdefault(record.size, []).append(record)

    excluded: dict[str, int] = {}
    candidate_groups = [
        (size, group)
        for size, group in sorted(by_size.items(), key=lambda kv: -kv[0])
        if len(group) >= 2
    ]

    groups: list[DuplicateGroup] = []
    budget = hash_budget_bytes

    for size, group in candidate_groups:
        hashed_outcomes: list[_HashOutcome] = []
        for record in group:
            if budget < size:
                excluded["budget_exceeded"] = excluded.get("budget_exceeded", 0) + 1
                continue
            outcome = _hash_and_guard(record)
            if outcome.reason == "hashed":
                budget -= size
                hashed_outcomes.append(outcome)
            else:
                # Failed members are excluded from THIS size group only;
                # other successful members may still form a verified group.
                excluded[outcome.reason] = excluded.get(outcome.reason, 0) + 1
        by_hash: dict[str, list[_HashOutcome]] = {}
        for outcome in hashed_outcomes:
            assert outcome.digest is not None
            by_hash.setdefault(outcome.digest, []).append(outcome)
        for digest, members in sorted(by_hash.items()):
            if len(members) >= 2:
                groups.append(
                    DuplicateGroup(
                        hash=digest,
                        size=size,
                        paths=[_as_str_path(m.path) for m in members],
                    )
                )

    # Sort groups by largest total size first, then alphabetically.
    groups.sort(key=lambda g: (-g.size * len(g.paths), g.paths[0].lower()))
    wasted_bytes = sum(g.size * (len(g.paths) - 1) for g in groups)
    return {
        "groups": [g.to_public() for g in groups],
        "excluded_counts": excluded,
        "duplicate_group_count": len(groups),
        "reclaimable_if_one_copy_removed": wasted_bytes,
    }
