"""Tests for the read-only filesystem scanner.

All destructive-risk tests use temporary directories with synthetic files.
Nothing here touches real user files.
"""

from __future__ import annotations

import hashlib
import os
import stat as stat_module
import types

import pytest

from app.core.paths import RootValidationError, validate_scan_root
from app.services import scanner as scanner_module
from app.services.scanner import Scanner


# ----------------------------------------------------------------------- fakes

class FakeDirContext:
    """Minimal stand-in for the object returned by os.scandir()."""

    def __init__(self, entries):
        self._entries = list(entries)

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, *exc_info):
        return False


class GhostEntry:
    """Entry that disappears between listing and stat (vanished file)."""

    def __init__(self, path: str, name: str):
        self.path = path
        self.name = name
        self._exc: BaseException | None = None

    def stat(self, follow_symlinks: bool = False):
        raise FileNotFoundError(self.path)

    def is_symlink(self) -> bool:
        return False


class MutatingEntry:
    """Entry whose size differs on consecutive stat calls (file changing
    mid-scan). The scanner must record a concrete snapshot and not fail."""

    def __init__(self, path: str, name: str, sizes: list[int]):
        self.path = path
        self.name = name
        self._sizes = list(sizes)
        self.calls = 0

    def stat(self, follow_symlinks: bool = False):
        size = self._sizes[min(self.calls, len(self._sizes) - 1)]
        self.calls += 1
        return types.SimpleNamespace(
            st_mode=stat_module.S_IFREG | 0o644,
            st_size=size,
            st_mtime=0.0,
            st_file_attributes=0,
        )

    def is_symlink(self) -> bool:
        return False


class ErroringEntry:
    """Entry whose stat raises an arbitrary OSError subclass."""

    def __init__(self, path: str, name: str, exc: BaseException):
        self.path = path
        self.name = name
        self._exc = exc

    def stat(self, follow_symlinks: bool = False):
        raise self._exc

    def is_symlink(self) -> bool:
        return False


class RealProxyEntry:
    """Delegates to a real os.DirEntry (path/name/stat/is_symlink only)."""

    def __init__(self, real):
        self._real = real

    @property
    def path(self):
        return self._real.path

    @property
    def name(self):
        return self._real.name

    def stat(self, follow_symlinks: bool = False):
        return self._real.stat(follow_symlinks)

    def is_symlink(self) -> bool:
        return self._real.is_symlink()


# --------------------------------------------------------------------- helpers

def write_file(path: str, size: int, fill: bytes = b"x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(fill * size)


def real_scandir():
    return scanner_module.os.scandir


def monkeypatch_scandir(monkeypatch, factory):
    monkeypatch.setattr(scanner_module, "SCANDIR", factory)


def norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def fake_skip_factory(skip_dir: str, entries_builder):
    """Scandir factory that replaces the listing of one directory."""
    real = real_scandir()
    target = norm(skip_dir)

    def factory(path):
        if norm(path) == target:
            return FakeDirContext(entries_builder(path, real))
        return real(path)

    return factory


# ---------------------------------------------------------------------- fixture

@pytest.fixture()
def sample_tree(tmp_path):
    root = str(tmp_path)
    write_file(os.path.join(root, "big.txt"), 1000)
    write_file(os.path.join(root, "a", "file1.txt"), 100)
    write_file(os.path.join(root, "a", "b", "file2.bin"), 250)
    write_file(os.path.join(root, "a", "b", "unicode 檔案.txt"), 5)
    os.makedirs(os.path.join(root, "empty"))
    return root


# ---------------------------------------------------------------------- tests

class TestBasicScanning:
    def test_recursive_scan_totals(self, sample_tree):
        s = Scanner([sample_tree]).run()
        assert s.summary()["file_count"] == 4
        assert s.summary()["bytes_scanned"] == 1000 + 100 + 250 + 5
        assert not s.cancelled

    def test_directory_rollup_matches_files(self, sample_tree):
        s = Scanner([sample_tree]).run()
        dirs = {os.path.basename(os.path.normcase(d.path)): d for d in s.directory_records()}
        # b holds file2.bin (250) + unicode 檔案.txt (5); a adds file1.txt (100).
        assert dirs["b"].total_size == 255
        assert dirs["b"].file_count == 2
        assert dirs["a"].total_size == 355
        assert dirs["a"].file_count == 3
        assert dirs["empty"].total_size == 0
        assert dirs["empty"].file_count == 0
        assert dirs["empty"] in s.directory_records()  # empty dir still recorded

    def test_file_records_carry_metadata(self, sample_tree):
        s = Scanner([sample_tree]).run()
        extensions = {f.extension for f in s.files}
        assert extensions == {".txt", ".bin"}
        big = next(f for f in s.files if f.path.endswith("big.txt"))
        on_disk = os.stat(big.path)
        assert big.size == 1000
        assert abs(big.mtime - on_disk.st_mtime) < 1.0
        uni_names = [f for f in s.files if "檔案" in f.path]
        assert len(uni_names) == 1 and uni_names[0].size == 5
        assert all("." in f.path for f in s.files)

    def test_scan_is_read_only(self, sample_tree):
        """Demonstration that scanning never modifies anything on disk."""
        def snapshot():
            state = {}
            for dirpath, _dirnames, filenames in os.walk(sample_tree):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    st = os.stat(full)
                    with open(full, "rb") as handle:
                        state[full] = (st.st_size, st.st_mtime_ns, hashlib.sha256(handle.read()).hexdigest())
            return state

        before = snapshot()
        Scanner([sample_tree]).run()
        after = snapshot()
        assert before == after

    def test_multiple_roots(self, tmp_path):
        root1 = str(tmp_path / "one")
        root2 = str(tmp_path / "two")
        write_file(os.path.join(root1, "f1.txt"), 10)
        write_file(os.path.join(root2, "f2.txt"), 20)
        s = Scanner([root1, root2]).run()
        assert s.summary()["bytes_scanned"] == 30
        assert s.summary()["file_count"] == 2

    def test_file_cap_stops_growth(self, tmp_path):
        root = str(tmp_path)
        for i in range(5):
            write_file(os.path.join(root, f"f{i}.txt"), 1)
        s = Scanner([root], max_files=3).run()
        assert len(s.files) == 3
        assert s.capped_files is True


class TestFaultTolerance:
    def test_missing_file_during_scan_is_skipped(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        write_file(os.path.join(root, "keep.txt"), 7)
        subdir = os.path.join(root, "sub")
        os.makedirs(subdir)
        write_file(os.path.join(subdir, "ghost.txt"), 3)  # listed but vanishes on stat
        factory = fake_skip_factory(subdir, lambda path, real: [
            GhostEntry(os.path.join(path, "ghost.txt"), "ghost.txt"),
        ] + [RealProxyEntry(e) for e in real(path) if e.name == "keep.txt"])
        monkeypatch_scandir(monkeypatch, factory)
        s = Scanner([root]).run()
        assert not s.cancelled
        assert s.summary()["file_count"] == 1  # only keep.txt
        assert s.skips.counts.get("missing") == 1

    def test_file_changing_during_scan_records_snapshot(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        subdir = os.path.join(root, "sub")
        os.makedirs(subdir)
        path = os.path.join(subdir, "growing.dat")
        with open(path, "wb") as handle:
            handle.write(b"x" * 10)
        factory = fake_skip_factory(subdir, lambda p, real: [
            MutatingEntry(path, "growing.dat", [10, 5000, 9000]),
        ])
        monkeypatch_scandir(monkeypatch, factory)
        s = Scanner([root]).run()
        assert s.summary()["file_count"] == 1
        assert s.files[0].size == 10  # one concrete snapshot, no crash

    def test_stat_os_error_is_skipped(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        os.makedirs(os.path.join(root, "sub"))
        factory = fake_skip_factory(os.path.join(root, "sub"), lambda p, real: [
            ErroringEntry(os.path.join(p, "weird.dat"), "weird.dat", OSError(22, "device error")),
        ])
        monkeypatch_scandir(monkeypatch, factory)
        s = Scanner([root]).run()
        assert s.skips.counts.get("stat_error") == 1
        assert s.summary()["file_count"] == 0

    def test_permission_error_on_nested_dir_is_skipped(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        good = os.path.join(root, "good")
        os.makedirs(good)
        write_file(os.path.join(good, "ok.txt"), 4)
        locked = os.path.join(root, "locked")
        os.makedirs(locked)
        write_file(os.path.join(locked, "secret.txt"), 9)

        real = real_scandir()
        locked_norm = norm(locked)

        def factory(path):
            if norm(path) == locked_norm:
                raise PermissionError(5, "Access is denied")
            return real(path)

        monkeypatch_scandir(monkeypatch, factory)
        s = Scanner([root]).run()
        assert s.summary()["file_count"] == 1  # good/ok.txt only
        assert s.skips.counts.get("permission_denied") == 1
        assert s.root_errors == []

    def test_permission_error_on_root_is_reported(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        real = real_scandir()
        target = norm(root)

        def factory(path):
            if norm(path) == target:
                raise PermissionError(5, "Access is denied")
            return real(path)

        monkeypatch_scandir(monkeypatch, factory)
        s = Scanner([root]).run()
        assert len(s.root_errors) == 1
        assert "Access is denied" in s.root_errors[0]
        assert s.summary()["file_count"] == 0


class TestReparseAndTraversalSafety:
    def test_symlinked_file_is_skipped(self, tmp_path):
        root = str(tmp_path)
        target_file = os.path.join(root, "..", "target.txt")
        write_file(target_file, 33)
        link = os.path.join(root, "link.txt")
        try:
            os.symlink(target_file, link)
        except OSError:
            pytest.skip("Symlink creation requires privileges/developer mode on this host")
        s = Scanner([root]).run()
        assert s.summary()["file_count"] == 0
        assert s.skips.counts.get("reparse_point") == 1

    def test_symlinked_directory_is_never_traversed(self, tmp_path):
        root = os.path.join(str(tmp_path), "root")
        outside = os.path.join(str(tmp_path), "outside")
        os.makedirs(root)
        os.makedirs(outside)
        write_file(os.path.join(outside, "outside_secret.txt"), 50)
        write_file(os.path.join(root, "inside.txt"), 10)
        link = os.path.join(root, "link-to-outside")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError:
            pytest.skip("Directory symlink requires privileges/developer mode on this host")
        s = Scanner([root]).run()
        names = [f.path for f in s.files]
        assert os.path.join(root, "inside.txt") in names
        assert all("outside_secret" not in n for n in names), "Traversal escaped the approved root via symlink"
        assert s.skips.counts.get("reparse_point") == 1

    def test_reparse_point_root_is_rejected(self, tmp_path):
        # A junction-like root must not be accepted via validation.
        with pytest.raises((RootValidationError, FileNotFoundError)):
            validate_scan_root(str(tmp_path / "does-not-exist"))

    def test_cycle_detection_terminates(self, tmp_path, monkeypatch):
        """A cycle between two real directories must be detected and cut."""
        root = str(tmp_path)
        loop_a = os.path.join(root, "loop_a")
        loop_b = os.path.join(root, "loop_b")
        os.makedirs(loop_a)
        os.makedirs(loop_b)

        real = real_scandir()

        class DirLikeEntry:
            def __init__(self, dir_path):
                self.path = dir_path
                self.name = os.path.basename(dir_path)

            def stat(self, follow_symlinks: bool = False):
                return os.stat(self.path, follow_symlinks=False)
            def is_symlink(self):
                return False

        def factory(path):
            base = norm(path)
            if base == norm(root):
                return FakeDirContext([DirLikeEntry(loop_a)])
            if base == norm(loop_a):
                return FakeDirContext([DirLikeEntry(loop_b)])
            if base == norm(loop_b):
                return FakeDirContext([DirLikeEntry(loop_a)])
            return real(path)

        monkeypatch_scandir(monkeypatch, factory)
        s = Scanner([root]).run()  # must terminate
        assert s.skips.counts.get("cycle_detected") == 1

    def test_depth_limit_stops_excessively_deep_trees(self, tmp_path):
        """A real nested chain deeper than the configured cap is cut at the
        depth limit instead of recursing forever."""
        root = str(tmp_path)
        parent = root
        for level in range(8):
            parent = os.path.join(parent, f"level{level}")
            os.makedirs(parent)
            write_file(os.path.join(parent, f"deep{level}.txt"), level + 1)
        s = Scanner([root], max_depth=3).run()
        assert s.skips.counts.get("depth_limit") == 1
        # Files above the cut are recorded; everything below is not.
        assert s.summary()["file_count"] == 3


class TestCancellation:
    def test_cancel_event_stops_scan(self, tmp_path):
        root = str(tmp_path)
        for i in range(20):
            write_file(os.path.join(root, f"f{i}.txt"), 1)
        event = scanner_module.threading.Event()
        event.set()  # cancel immediately
        s = Scanner([root], cancel_event=event).run()
        assert s.cancelled is True
        assert len(s.files) < 20


class TestRootValidation:
    def test_rejects_empty(self):
        with pytest.raises(RootValidationError):
            validate_scan_root("")

    def test_rejects_relative_path(self):
        with pytest.raises(RootValidationError):
            validate_scan_root("relative/path")

    def test_rejects_nonexistent(self, tmp_path):
        with pytest.raises(RootValidationError):
            validate_scan_root(str(tmp_path / "nope"))

    def test_rejects_file_not_directory(self, tmp_path):
        target = tmp_path / "file.txt"
        target.write_text("x")
        with pytest.raises(RootValidationError):
            validate_scan_root(str(target))

    def test_rejects_symlink_root(self, tmp_path):
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "f.txt").write_text("x")
        link = tmp_path / "linked"
        try:
            os.symlink(str(real_dir), str(link), target_is_directory=True)
        except OSError:
            pytest.skip("Directory symlink requires privileges/developer mode on this host")
        with pytest.raises(RootValidationError):
            validate_scan_root(str(link))

    def test_accepts_real_directory(self, tmp_path):
        assert validate_scan_root(str(tmp_path)) == os.path.abspath(str(tmp_path))
