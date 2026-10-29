"""Protected-path checks and canonical-path validation (Phase 2).

Policy primitives used by the cleanup classification service. These checks
are cheap, deterministic, and conservative: if a path cannot be resolved or
verified, the caller must treat it as unsafe/review.
"""

from __future__ import annotations

import os

# Mirrors stat.FILE_ATTRIBUTE_REPARSE_POINT.
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Exact protected system files at drive-root level.
PROTECTED_SYSTEM_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "memory.dmp"}

_BODY = os.path.normcase


def _env_paths(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        value = os.environ.get(name)
        if value:
            out.append(os.path.abspath(value))
    return out


def protected_prefixes() -> list[str]:
    """Canonical protected directory prefixes on this platform.

    Windows system directories, application installation locations, and
    global program data. Built from environment variables first, with
    conventional fallbacks so the policy stays correct even when an env var
    is missing. All comparisons use normcase (case-insensitive on Windows).
    """
    env = os.environ
    system_drive = env.get("SystemDrive", "C:")
    candidates = _env_paths(
        ["SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"]
    )
    candidates += [
        os.path.join(system_drive, "Windows"),
        os.path.join(system_drive, "Program Files"),
        os.path.join(system_drive, "Program Files (x86)"),
        os.path.join(system_drive, "ProgramData"),
    ]
    # Per-drive system folders, plus POSIX system roots so the policy remains
    # safe if the app is ported to other platforms later.
    candidates += [
        os.path.join(system_drive, "$Recycle.Bin"),
        os.path.join(system_drive, "System Volume Information"),
        "/usr",
        "/etc",
        "/bin",
        "/sbin",
        "/lib",
        "/opt",
        "/var",
        "/System",
        "/Library",
    ]
    normalized: list[str] = []
    for candidate in candidates:
        absolute = _BODY(os.path.abspath(candidate))
        if absolute not in normalized:
            normalized.append(absolute)
    return normalized


def canonical_path(path: str) -> str | None:
    """Return the canonical absolute path, or None when it cannot be
    resolved (committed missing, or real path resolution failed).

    realpath resolves symlinks and normalizes case/separators on Windows,
    which is exactly the canonical form protection checks must be applied
    against — never against the raw user- or scan-supplied string.
    """
    try:
        resolved = os.path.realpath(os.path.abspath(path))
    except OSError:
        return None
    return _BODY(resolved) if os.path.exists(resolved) else None


def is_protected_system_path(path: str) -> bool:
    """True when path is a system/application install location or a protected
    system file (pagefile.sys etc.), verified against the canonical path."""
    canonical = canonical_path(path)
    if canonical is None:
        return False
    for prefix in protected_prefixes():
        if canonical == prefix or canonical.startswith(prefix + os.sep):
            return True
    drive, tail = os.path.splitdrive(canonical)
    if drive and os.path.basename(tail) in PROTECTED_SYSTEM_FILES:
        return True
    return False


def within_root(path: str, root: str) -> bool:
    """True when canonical(path) is root itself or strictly below it."""
    canonical = canonical_path(path)
    root_canonical = _BODY(os.path.abspath(root))
    return canonical is not None and (
        canonical == root_canonical or canonical.startswith(root_canonical + os.sep)
    )


def canonical_root(root: str) -> str:
    """Canonical form of an approved root: realpath-resolved and normcased,
    falling back to abspath when realpath cannot verify it (root deleted
    mid-analysis, for instance).

    Roots must be canonicalized with the same machinery as candidates — if a
    root directory were later replaced by a junction, containment computed
    against its abspath alone would trust a path that no longer lives there.
    """
    resolved = os.path.realpath(os.path.abspath(root))
    return _BODY(resolved)


def protection_violations(path: str, approved_roots: list[str]) -> list[str]:
    """All reasons a path may not participate in cleanup.

    Empty list means every check passed *right now*. Callers must still
    revalidate immediately before any destructive action in later phases —
    this phase introduces classification only, never deletion.
    """
    violations: list[str] = []
    # Boundary check uses the raw absolute form too: a missing file still
    # must not be treated as "inside" an approved root if its spelled path
    # already points outside. Existence itself is (re)validated at execution
    # time in a later phase.
    raw = _BODY(os.path.abspath(path))
    canonical = canonical_path(path)
    # Approved roots are also resolved through realpath (A-4): containment
    # must hold for the REAL directory behind each root, not just the string
    # that was approved, so a later junction swap cannot silently widen the
    # trust boundary.
    approved = [canonical_root(root) for root in approved_roots]
    inside_raw = any(raw == root or raw.startswith(root + os.sep) for root in approved)
    inside_canonical = canonical is not None and any(
        canonical == root or canonical.startswith(root + os.sep) for root in approved
    )
    if not inside_raw:
        violations.append("outside_approved_roots")
    elif canonical is not None and not inside_canonical:
        # An existing file whose canonical path resolves outside the roots
        # (e.g. reached through a link) is outside, whatever its spelling.
        violations.append("outside_approved_roots")
    if canonical is not None and is_protected_system_path(canonical):
        violations.append("protected_system_path")
    try:
        if canonical is None:
            st = None
        else:
            st = os.stat(canonical, follow_symlinks=False)
    except OSError:
        # A missing file is not a deletion hazard; cleanup revalidation in a
        # later phase decides existence at execution time.
        st = None
    if st is not None and (
        getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT or os.path.islink(canonical)
    ):
        violations.append("reparse_point")
    # UNC paths cannot be meaningfully verified against approved local roots,
    # so treat them as unverifiable and therefore unsafe.
    if raw.startswith("\\\\"):
        violations.append("unc_path")
    return violations
