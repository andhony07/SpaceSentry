"""Path validation for scan roots and (in later phases) cleanup targets.

Phase 1 scope: validating scan roots only. Cleanup-path policy arrives in
Phase 4 and will build on these primitives.
"""

from __future__ import annotations

import os

FILE_ATTRIBUTE_REPARSE_POINT = 0x400  # mirrors stat.FILE_ATTRIBUTE_REPARSE_POINT


class RootValidationError(ValueError):
    """Raised when a requested scan root is not safe to scan."""


def is_reparse_point(path: str) -> bool:
    """True if path is a symlink or any other reparse point (junction,
    mounted folder, etc.). Reparse points can redirect traversal outside
    approved boundaries and are therefore never followed."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT) or os.path.islink(path)


def validate_scan_root(path: str) -> str:
    """Validate a user-selected scan root and return its absolute form.

    Rules (Phase 1):
    - must be an absolute path,
    - must exist and be a directory,
    - must not be a reparse point (symlink/junction),
    - must not be a drive-relative or UNC-rooted alias with no directory.
    """
    if not path or not path.strip():
        raise RootValidationError("Scan root cannot be empty.")
    candidate = os.path.abspath(path)
    if not os.path.isabs(candidate):
        raise RootValidationError(f"Scan root must be an absolute path: {path}")
    if not os.path.exists(candidate):
        raise RootValidationError(f"Scan root does not exist: {candidate}")
    if not os.path.isdir(candidate):
        raise RootValidationError(f"Scan root is not a directory: {candidate}")
    if is_reparse_point(candidate):
        raise RootValidationError(f"Scan root is a symlink or reparse point, not a real directory: {candidate}")
    return candidate
