"""Large-file analysis over completed Phase 1 scan results (read-only).

Ranks files by actual recorded byte size. Sizes come exclusively from the
scanner's ``stat`` records — nothing is estimated or fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.scanner import FileRecord


@dataclass
class LargeFileFinding:
    path: str
    size: int
    extension: str
    mtime: float

    def to_public(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "extension": self.extension,
            "mtime": self.mtime,
        }


def analyze_large_files(
    files: list[FileRecord],
    *,
    min_size_bytes: int = 0,
    limit: int = 50,
) -> dict:
    """Deterministic largest-file ranking.

    - ``min_size_bytes`` filters on the recorded size (inclusive).
    - ``limit`` caps output after sorting (descending by size, ties broken
      by path for determinism).
    - Empty or incomplete input simply yields an empty list; sizes are
      never invented.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    if min_size_bytes < 0:
        raise ValueError("min_size_bytes cannot be negative")
    eligible = [f for f in files if f.size >= min_size_bytes]
    eligible.sort(key=lambda f: (-f.size, f.path.lower(), f.path))
    selected = eligible[:limit]
    return {
        "total_files": len(files),
        "eligible_count": len(eligible),
        "total_eligible_bytes": sum(f.size for f in eligible),
        "files": [
            LargeFileFinding(
                path=f.path,
                size=f.size,
                extension=f.extension,
                mtime=f.mtime,
            ).to_public()
            for f in selected
        ],
        "truncated": len(eligible) > len(selected),
    }
