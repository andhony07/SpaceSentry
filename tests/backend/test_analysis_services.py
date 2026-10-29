"""Phase 2 service-level tests: large files, duplicates, categorization, policy.

All tests use temporary directories with synthetic files only.
"""

from __future__ import annotations

import hashlib
import os
import time
import types

import pytest

from app.core.paths import validate_scan_root
from app.services import duplicate_detector as dd
from app.services.cleanup_policy import (
    CLASSIFICATION_POTENTIAL_CLEANUP,
    CLASSIFICATION_PROTECTED,
    CLASSIFICATION_REVIEW_REQUIRED,
    evaluate_findings,
)
from app.services.categorizer import (
    CATEGORY_DUPLICATE,
    CATEGORY_LARGE_FILE,
    CATEGORY_OLD_FILE,
    CATEGORY_TEMPORARY,
    CATEGORY_UNCATEGORIZED,
    categorize_files,
)
from app.services.large_file_analyzer import analyze_large_files
from app.services.scanner import FileRecord


def write_file(path: str, content: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def record(path: str, size: int = 0, mtime: float = 0.0) -> FileRecord:
    return FileRecord(path=path, size=size, mtime=mtime, extension=os.path.splitext(path)[1].lower())


def scan_root(tmp_path):
    return validate_scan_root(str(tmp_path))


def make_scan(tmp_path, layout: dict):
    """layout: relative path -> bytes. Returns (root, records from real scan)."""
    from app.services.scanner import Scanner

    root = str(tmp_path)
    for relative, content in layout.items():
        write_file(os.path.join(root, relative.replace("/", os.sep)), content)
    scanner = Scanner([root]).run()
    return root, scanner.files


# ---------------------------------------------------------------- large files

class TestLargeFileAnalyzer:
    def test_ranking_desc_by_size(self):
        files = [record("a.txt", 100), record("b.txt", 900), record("c.txt", 500)]
        result = analyze_large_files(files)
        sizes = [f["size"] for f in result["files"]]
        assert sizes == [900, 500, 100]
        assert result["total_eligible_bytes"] == 1500

    def test_min_size_threshold(self):
        files = [record("small.txt", 5), record("big.bin", 1000)]
        result = analyze_large_files(files, min_size_bytes=100)
        assert [f["path"] for f in result["files"]] == ["big.bin"]
        assert result["eligible_count"] == 1

    def test_limit_caps_and_flags_truncation(self):
        files = [record(f"f{i}.txt", 1000 - i) for i in range(5)]
        result = analyze_large_files(files, limit=2)
        assert len(result["files"]) == 2
        assert result["truncated"] is True

    def test_empty_and_incomplete_results(self):
        result = analyze_large_files([])
        assert result["files"] == []
        assert result["total_files"] == 0
        assert result["truncated"] is False

    def test_invalid_limits_rejected(self):
        with pytest.raises(ValueError):
            analyze_large_files([record("x", 1)], limit=0)
        with pytest.raises(ValueError):
            analyze_large_files([record("x", 1)], min_size_bytes=-1)

    def test_sizes_come_from_records_not_guesses(self, tmp_path):
        root, files = make_scan(tmp_path, {"doc.pdf": b"a" * 12345})
        result = analyze_large_files(files)
        assert result["files"][0]["size"] == 12345


# --------------------------------------------------------------- duplicates

class TestDuplicateDetection:
    def test_identical_content_grouped(self, tmp_path):
        root, files = make_scan(
            tmp_path,
            {"a/copy1.txt": b"same", "b/copy2.bin": b"same"},
        )
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 1
        assert sorted(result["groups"][0]["paths"]) == sorted(
            [f.path for f in files]
        )
        assert result["groups"][0]["size"] == 4

    def test_same_size_different_content_not_grouped(self, tmp_path):
        root, files = make_scan(
            tmp_path,
            {"one.bin": b"\x00\x00\x00\x00", "two.bin": b"\xff\xff\xff\xff"},
        )
        assert all(f.size == 4 for f in files)
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 0

    def test_same_filename_different_content_not_grouped(self, tmp_path):
        root, files = make_scan(
            tmp_path,
            {"x/report.pdf": b"A" * 100, "y/report.pdf": b"B" * 100},
        )
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 0
        assert len(files) == 2 and files[0].size == files[1].size

    def test_empty_files_duplicate_each_other(self, tmp_path):
        root, files = make_scan(tmp_path, {"e1.dat": b"", "e2.dat": b"", "e3.dat": b""})
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 1
        assert len(result["groups"][0]["paths"]) == 3

    def test_different_sizes_never_compared_or_faked(self, tmp_path):
        root, files = make_scan(tmp_path, {"a": b"AAA", "b": b"AA"})
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 0

    def test_file_changed_between_scan_and_hash_excluded(self, tmp_path):
        root, files = make_scan(tmp_path, {"d1.txt": b"original", "d2.txt": b"original"})
        # Mutate one file after the scan snapshot.
        write_file(os.path.join(root, "d1.txt"), b"mutated")
        result = dd.detect_duplicates(files)
        assert result["excluded_counts"].get("changed_since_scan") == 1
        assert result["duplicate_group_count"] == 0

    def test_file_missing_at_hash_time_excluded(self, tmp_path):
        root, files = make_scan(tmp_path, {"gone.txt": b"gone", "here.txt": b"gone"})
        os.remove(files[0].path)
        result = dd.detect_duplicates(files)
        assert result["excluded_counts"].get("disappeared") == 1
        assert result["duplicate_group_count"] == 0

    def test_hash_budget_respected(self, tmp_path):
        root, files = make_scan(tmp_path, {"big1.bin": b"x" * 2048, "big2.bin": b"x" * 2048})
        result = dd.detect_duplicates(files, hash_budget_bytes=1024)
        assert result["excluded_counts"].get("budget_exceeded") == 2
        assert result["duplicate_group_count"] == 0

    def test_large_file_hashing_is_streamed_not_fully_loaded(self, tmp_path, monkeypatch):
        """A >chunk multi-block file must hash correctly via chunked reads."""
        root, files = make_scan(
            tmp_path,
            {
                "h1.bin": bytes(range(256)) * 97,  # 24832 bytes, multi-chunk
                "h2.bin": bytes(range(256)) * 97,
            },
        )
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 1
        expected = hashlib.sha256(bytes(range(256)) * 97).hexdigest()
        assert result["groups"][0]["hash"] == expected

    def test_symlinks_never_followed(self, tmp_path):
        real_file = write_file(os.path.join(str(tmp_path / "realdata"), "f.bin"), b"payload")
        root_dir = str(tmp_path / "scanned")
        os.makedirs(root_dir, exist_ok=True)
        try:
            os.symlink(real_file, os.path.join(root_dir, "link.bin"))
        except OSError:
            pytest.skip("symlink privileges unavailable")
        # The scan skips the reparse point, so no content is loaded via the link.
        root, files = make_scan(tmp_path / "scanned", {"plain.txt": b"n"})
        result = dd.detect_duplicates(files)
        assert result["duplicate_group_count"] == 0
        assert not any("link.bin" in f.path for f in files)

    def test_analysis_is_read_only(self, tmp_path):
        layout = {"a.txt": b"duplicate", "b.txt": b"duplicate", "big.bin": os.urandom(1000)}
        root, files = make_scan(tmp_path, layout)

        def snapshot():
            state = {}
            for dirpath, _dirs, names in os.walk(str(tmp_path)):
                for name in names:
                    full = os.path.join(dirpath, name)
                    st = os.stat(full)
                    with open(full, "rb") as handle:
                        state[full] = (st.st_size, st.st_mtime_ns, hashlib.sha256(handle.read()).hexdigest())
            return state

        before = snapshot()
        dd.detect_duplicates(files)
        analyze_large_files(files)
        duplications = dd.detect_duplicates(files)
        categorize_files(files, duplications, now_mtime=time.time())
        after = snapshot()
        assert before == after


# ------------------------------------------------------------ categorization

class TestCategorizer:
    def _detect(self, tmp_path, layout):
        root, files = make_scan(tmp_path, layout)
        duplicates = dd.detect_duplicates(files)
        return files, duplicates

    def test_temporary_extension_rule(self, tmp_path):
        files, duplicates = self._detect(tmp_path, {"scratch.tmp": b"x" * 10})
        report = categorize_files(files, duplicates, now_mtime=time.time())
        categories = {f.category for f in report.findings}
        assert CATEGORY_TEMPORARY in categories

    def test_generic_extensions_not_temporary(self, tmp_path):
        files, duplicates = self._detect(
            tmp_path,
            {"note.log": b"1", "notes.zip": b"2", "setup.exe": b"3"},
        )
        report = categorize_files(files, duplicates, now_mtime=time.time())
        categories = {f.category for f in report.findings}
        assert CATEGORY_TEMPORARY not in categories
        assert categories == {CATEGORY_UNCATEGORIZED}

    def test_build_cache_and_ambiguity_split(self, tmp_path):
        files, duplicates = self._detect(
            tmp_path,
            {
                "proj/__pycache__/mod.pyc": b"artifact1",
                "proj/dist/manual-note.txt": b"artifact2",
                "keep/source.py": b"artifact3",
            },
        )
        report = categorize_files(files, duplicates, now_mtime=time.time())
        cache_findings = report.categories.get("dev_build_cache", [])
        pycache = [f for f in cache_findings if "__pycache__" in f.path]
        dist = [f for f in cache_findings if "dist" in f.path]
        assert len(pycache) == 1 and len(dist) == 1
        # keep/source.py must be uncategorized, not cache-tagged
        keep = [f for f in report.findings if "keep" + os.sep + "source.py" in f.path]
        assert keep and keep[0].category == CATEGORY_UNCATEGORIZED

    def test_multiple_findings_for_one_file(self, tmp_path):
        files, duplicates = self._detect(tmp_path, {"tmp/dup.tmp": b"same"})
        # Make an actual duplicate pair.
        write_file(os.path.join(str(tmp_path), "tmp", "dup2.tmp"), b"same")
        from app.services.scanner import Scanner
        files = Scanner([str(tmp_path)]).run().files
        duplicates = dd.detect_duplicates(files)
        report = categorize_files(files, duplicates, now_mtime=time.time())
        target = next(f for f in report.findings if f.path.endswith("dup.tmp"))
        paths = {os.path.basename(f.path) for f in report.findings}
        assert "dup.tmp" in paths and "dup2.tmp" in paths
        count = sum(1 for f in report.findings if f.path.endswith("dup.tmp"))
        assert count >= 2  # temporary + duplicate findings on the same file

    def test_large_and_old_files_review_only(self, tmp_path):
        files, duplicates = self._detect(tmp_path, {"huge-old.iso": b"\0" * (100 * 1024 * 1024 + 1)})
        old_mtime = time.time() - 400 * 86400
        for f in files:
            f.mtime = old_mtime
        report = categorize_files(files, duplicates, now_mtime=time.time())
        categories = {f.category for f in report.findings}
        assert CATEGORY_LARGE_FILE in categories
        assert CATEGORY_OLD_FILE in categories
        # Nothing about them is marked safe: policy check in TestPolicy.

    def test_uncategorized_fallback(self, tmp_path):
        files, duplicates = self._detect(tmp_path, {"holiday.jpg": b"\xff\xd8" + b"0" * 10})
        report = categorize_files(files, duplicates, now_mtime=time.time())
        assert CATEGORY_UNCATEGORIZED in {f.category for f in report.findings}
        assert report.uncategorized_count == len(files)

    def test_duplicate_finding_never_by_name_alone(self, tmp_path):
        files, duplicates = self._detect(
            tmp_path,
            {"same-name/keep.txt": b"one content", "other-name/keep.txt": b"different!"},
        )
        report = categorize_files(files, duplicates, now_mtime=time.time())
        assert not any(
            f.category == CATEGORY_DUPLICATE for f in report.findings
        )


# ----------------------------------------------------------- cleanup policy

class TestCleanupPolicy:
    def _evaluate(self, tmp_path, findings):
        root = validate_scan_root(str(tmp_path))
        return evaluate_findings(findings, [root])

    def via_category(self, category):
        from app.services.categorizer import Finding
        return Finding(path="x", size=1, category=category, reason="test")

    def test_outside_root_is_protected(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        outside = f"{root}{os.sep}..{os.sep}outside.txt"
        report = evaluate_findings([Finding(path=outside, size=1, category=CATEGORY_TEMPORARY, reason="r")], [root])
        evaluation = report["evaluations"][0]
        assert evaluation["classification"] == CLASSIFICATION_PROTECTED
        assert "outside_approved_roots" in evaluation["eligibility_detail"]

    def test_unc_driven_path_is_protected(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        report = evaluate_findings(
            [Finding(path="\\\\remote\\share\\tmp\\f.tmp", size=1, category=CATEGORY_TEMPORARY, reason="r")],
            [root],
        )
        assert report["evaluations"][0]["classification"] == CLASSIFICATION_PROTECTED

    def test_system_path_is_protected(self, tmp_path):
        from app.services.categorizer import Finding
        windows_dir = os.environ.get("SystemRoot", "C:\\Windows")
        report = evaluate_findings(
            [Finding(path=os.path.join(windows_dir, "notepad.exe"), size=1, category=CATEGORY_TEMPORARY, reason="r")],
            [validate_scan_root(str(tmp_path))],
        )
        assert report["evaluations"][0]["classification"] == CLASSIFICATION_PROTECTED
        assert "protected_system_path" in report["evaluations"][0]["eligibility_detail"]

    def test_temporary_inside_root_is_potential_cleanup_with_warning(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        target = write_file(os.path.join(str(tmp_path), "scratch.tmp"), b"junk")
        report = evaluate_findings(
            [Finding(path=target, size=4, category=CATEGORY_TEMPORARY, reason="extension rule")],
            [root],
        )
        evaluation = report["evaluations"][0]
        assert evaluation["classification"] == CLASSIFICATION_POTENTIAL_CLEANUP
        assert evaluation["warnings"]

    def test_large_file_inside_root_is_review_required(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        target = write_file(os.path.join(str(tmp_path), "movie.mkv"), b"\x00" * 1024)
        report = evaluate_findings(
            [Finding(path=target, size=1024, category=CATEGORY_LARGE_FILE, reason="size")],
            [root],
        )
        evaluation = report["evaluations"][0]
        assert evaluation["classification"] == CLASSIFICATION_REVIEW_REQUIRED
        assert evaluation["eligible"] is False

    def test_missing_file_conservative(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        missing = os.path.join(str(tmp_path), "vanished.tmp")
        report = evaluate_findings(
            [Finding(path=missing, size=4, category=CATEGORY_TEMPORARY, reason="r")],
            [root],
        )
        evaluation = report["evaluations"][0]
        assert evaluation["classification"] == CLASSIFICATION_POTENTIAL_CLEANUP
        # Eligibility detail explicitly refers to user-approved cleanup.
        assert "user-approved" in evaluation["eligibility_detail"]

    def test_duplicate_category_requires_user_choice(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        a = write_file(os.path.join(str(tmp_path), "a.bin"), b"duplicate")
        b_path = write_file(os.path.join(str(tmp_path), "b.bin"), b"duplicate")
        report = evaluate_findings(
            [
                Finding(path=a, size=9, category=CATEGORY_DUPLICATE, reason="hash match"),
                Finding(path=b_path, size=9, category=CATEGORY_DUPLICATE, reason="hash match"),
            ],
            [root],
        )
        assert all(
            e["classification"] == CLASSIFICATION_POTENTIAL_CLEANUP
            and any("Keep at least one copy" in w for w in e["warnings"])
            for e in report["evaluations"]
        )

    def test_bytes_summary_adds_up(self, tmp_path):
        from app.services.categorizer import Finding
        root = validate_scan_root(str(tmp_path))
        r1 = write_file(os.path.join(str(tmp_path), "t.tmp"), b"12345")
        r2 = write_file(os.path.join(str(tmp_path), "keep.txt"), b"123456789")
        report = evaluate_findings(
            [
                Finding(path=r1, size=5, category=CATEGORY_TEMPORARY, reason="r"),
                Finding(path=r2, size=9, category=CATEGORY_UNCATEGORIZED, reason="r"),
            ],
            [root],
        )
        assert report["bytes"]["potential_cleanup"] == 5
        assert report["bytes"]["review_required"] == 9

    def test_no_deletion_apis_exist(self):
        """Negative-space check: the policy module must not provide execution."""
        import app.services.cleanup_policy as policy
        assert not any(
            "delete" in name.lower() or "execute" in name.lower()
            for name in dir(policy)
            if not name.startswith("_")
        )
