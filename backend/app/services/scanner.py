"""Recursive, read-only filesystem scanner for SpaceSentry.

Safety properties
-----------------
- Read-only: uses only ``os.scandir`` and ``stat``. Files are never opened,
  moved, renamed, or deleted; nothing on disk is modified.
- Root-bounded: traversal starts only at validated scan roots and never
  follows entries outside them.
- Reparse-safe: symlinks and other reparse points (NTFS junctions, mounted
  folders) are skipped by default so traversal cannot escape approved roots.
- Loop-safe: cyclic directory graphs are detected via ``(st_dev, st_ino)``
  identity, plus a hard depth limit.
- Fault-tolerant: permission errors, vanished files, and files that change
  mid-scan are recorded as skips instead of aborting the whole scan.
- Cancellable: cooperative cancellation through ``threading.Event``.
- Bounded: caps on files and directories guard against pathological trees.

Uniformity note: directory roll-up totals are computed from the recorded
file records after traversal, so every size is derived from the same
snapshot and is deterministic for the recorded data.
"""

from __future__ import annotations

import logging
import os
import stat as stat_module
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Module-level indirection so tests can deterministically inject I/O faults.
SCANDIR = os.scandir

# Windows reparse-point attribute (symlinks, junctions, mounted folders).
# Guarded getattr so this module also imports on non-Windows hosts.
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

DEFAULT_MAX_DEPTH = 64
DEFAULT_MAX_FILES = 200_000
DEFAULT_MAX_DIRS = 100_000
MAX_SKIP_SAMPLES = 20


class ScanCancelled(Exception):
    """Internal signal raised when cooperative cancellation is requested."""


@dataclass
class FileRecord:
    path: str
    size: int
    mtime: float
    extension: str
    # Nanosecond-resolution modification time, needed for exact identity
    # revalidation (float mtime loses precision at ns epoch scale).
    mtime_ns: int = 0
    status: str = "ok"


@dataclass
class DirectoryRecord:
    path: str
    total_size: int = 0
    file_count: int = 0


@dataclass
class SkipSummary:
    """Counts and bounded samples of entries that could not be scanned."""

    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)

    def record(self, reason: str, path: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1
        samples = self.samples.setdefault(reason, [])
        if len(samples) < MAX_SKIP_SAMPLES:
            samples.append(path)

    @property
    def total_skipped(self) -> int:
        return sum(self.counts.values())

    def to_public(self) -> dict:
        return {"counts": dict(self.counts), "samples": {k: list(v) for k, v in self.samples.items()}}


@dataclass
class ScanProgress:
    files_scanned: int = 0
    bytes_scanned: int = 0
    directories_scanned: int = 0
    files_skipped: int = 0
    current_root: str | None = None
    current_path: str | None = None

    def to_public(self) -> dict:
        return {
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "directories_scanned": self.directories_scanned,
            "files_skipped": self.files_skipped,
            "current_root": self.current_root,
            "current_path": self.current_path,
        }


class Scanner:
    """Read-only recursive scanner over one or more validated roots."""

    def __init__(
        self,
        roots: list[str],
        cancel_event: threading.Event | None = None,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_files: int = DEFAULT_MAX_FILES,
        max_dirs: int = DEFAULT_MAX_DIRS,
    ) -> None:
        self.roots = [os.path.abspath(r) for r in roots]
        self._cancel = cancel_event or threading.Event()
        self.max_depth = max_depth
        self.max_files = max_files
        self.max_dirs = max_dirs

        self.files: list[FileRecord] = []
        # Keyed by normcase(abspath) so ancestor lookups are reliable on
        # case-insensitive Windows filesystems.
        self._dirs: dict[str, DirectoryRecord] = {}
        self.skips = SkipSummary()
        self.progress = ScanProgress()
        self._visited: set[tuple[int, int]] = set()
        self.root_errors: list[str] = []
        self.cancelled = False
        self.capped_files = False
        self._roll_up_done = False

    # ------------------------------------------------------------------ run

    def run(self) -> "Scanner":
        for root in self.roots:
            self.progress.current_root = root
            try:
                self._explore(root, depth=0)
            except ScanCancelled:
                self.cancelled = True
                logger.info("Scan cancelled at %s", root)
                break
            except OSError as exc:
                # The root itself could not be listed; record it and continue
                # with remaining roots instead of failing the whole scan.
                self.root_errors.append(f"{root}: {type(exc).__name__}: {exc}")
                logger.warning("Root %s could not be scanned: %s", root, exc)
        self._roll_up()
        return self

    def summary(self) -> dict:
        pct = 100.0 * self.progress.files_scanned / max(1, self.progress.files_scanned)
        return {
            "roots": list(self.roots),
            "file_count": len(self.files),
            "bytes_scanned": self.progress.bytes_scanned,
            "directory_count": len(self._dirs),
            "skipped": self.skips.to_public(),
            "root_errors": list(self.root_errors),
            "cancelled": self.cancelled,
            "capped_files": self.capped_files,
        }

    # -------------------------------------------------------------- traversal

    def _check_cancellation(self) -> None:
        if self._cancel.is_set():
            raise ScanCancelled()

    def _explore(self, path: str, depth: int) -> None:
        self._check_cancellation()

        abs_path = os.path.abspath(path)
        if depth > self.max_depth:
            self.skips.record("depth_limit", abs_path)
            return

        identity = self._directory_identity(abs_path)
        if identity is None:
            return  # reason already recorded

        if identity in self._visited:
            self.skips.record("cycle_detected", abs_path)
            return
        self._visited.add(identity)

        if not self._register_directory(abs_path):
            return  # could not be listed; skip reason already recorded

        self.progress.directories_scanned += 1
        self.progress.current_path = abs_path

        try:
            with SCANDIR(abs_path) as iterator:
                entries = list(iterator)
        except PermissionError:
            if depth == 0:
                raise  # surface the original error for root-level reporting
            self.skips.record("permission_denied", abs_path)
            self.progress.files_skipped += 1
            return
        except OSError:
            if depth == 0:
                raise
            self.skips.record("os_error", abs_path)
            self.progress.files_skipped += 1
            return

        for entry in entries:
            if self._cancel.is_set():
                raise ScanCancelled()
            if len(self.files) >= self.max_files:
                self.capped_files = True
                self.skips.record("file_cap", abs_path)
                return
            self._process_entry(entry, depth + 1)

    def _process_entry(self, entry, depth: int) -> None:
        try:
            st = entry.stat(follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError):
            # File disappeared or mutated between listing and stat.
            self.skips.record("missing", entry.path)
            self.progress.files_skipped += 1
            return
        except OSError:
            self.skips.record("stat_error", entry.path)
            self.progress.files_skipped += 1
            return

        if self._is_reparse(entry, st):
            self.skips.record("reparse_point", entry.path)
            self.progress.files_skipped += 1
            return

        mode = st.st_mode
        if stat_module.S_ISDIR(mode):
            if len(self._dirs) >= self.max_dirs:
                self.skips.record("dir_cap", entry.path)
            else:
                self._explore(entry.path, depth)
        elif stat_module.S_ISREG(mode):
            self._record_file(entry, st)
        else:
            self.skips.record("special", entry.path)
            self.progress.files_skipped += 1

    # ------------------------------------------------------------- helpers

    def _is_reparse(self, entry, st) -> bool:
        if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            return True
        # Non-Windows fallback (and belt-and-braces on Windows).
        return entry.is_symlink()

    def _directory_identity(self, abs_path: str) -> tuple[int, int] | None:
        """Return the identity key used for loop detection, or None if the
        directory cannot be reliably identified."""
        try:
            st = os.stat(abs_path, follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError):
            self.skips.record("missing", abs_path)
            if abs_path in [os.path.abspath(r) for r in self.roots]:
                self.root_errors.append(f"{abs_path}: disappeared before scan")
            return None
        except OSError:
            self.skips.record("os_error", abs_path)
            return None
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            # A reparse-point root would let traversal escape approved
            # boundaries, so it is never followed.
            self.root_errors.append(f"{abs_path}: reparse-point directories are not accepted as roots")
            return None
        return (int(st.st_dev), int(st.st_ino))

    def _register_directory(self, abs_path: str) -> bool:
        key = os.path.normcase(abs_path)
        if key not in self._dirs:
            self._dirs[key] = DirectoryRecord(path=abs_path)
        return True

    def _record_file(self, entry, st) -> None:
        path = entry.path
        extension = os.path.splitext(entry.name)[1].lower()
        self.files.append(
            FileRecord(
                path=path,
                size=st.st_size,
                mtime=st.st_mtime,
                mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
                extension=extension,
            )
        )
        self.progress.files_scanned += 1
        self.progress.bytes_scanned += st.st_size

    def _roll_up(self) -> None:
        """Propagate every recorded file size into all ancestor directories
        that live inside the scanned roots. This is what makes per-directory
        totals consistent with the per-file numbers on the dashboard."""
        if self._roll_up_done:
            return
        self._roll_up_done = True
        for file_record in self.files:
            directory = os.path.dirname(file_record.path)
            while True:
                key = os.path.normcase(directory)
                record = self._dirs.get(key)
                if record is None:
                    break  # above the scanned roots
                record.total_size += file_record.size
                record.file_count += 1
                parent = os.path.dirname(directory)
                if parent == directory:
                    break
                directory = parent

    def directory_records(self) -> list[DirectoryRecord]:
        return list(self._dirs.values())
