"""Regression tests from the Phase 2 security audit (A-1..A-5).

Every test here corresponds to a confirmed finding and would fail on the
pre-fix implementation.
"""

from __future__ import annotations

import os
import stat as stat_module
import types
import pytest
from fastapi.testclient import TestClient

from app.core.protected_paths import protection_violations
from app.main import app
from app.services import duplicate_detector as dd
from app.services.cleanup_policy import (
    CLASSIFICATION_POTENTIAL_CLEANUP,
    CLASSIFICATION_PROTECTED,
    CLASSIFICATION_REVIEW_REQUIRED,
    evaluate_finding,
)
from app.services.categorizer import CATEGORY_TEMPORARY, Finding
from app.services.scanner import FileRecord

client = TestClient(app, base_url="http://127.0.0.1:8765")


def write_file(path: str, content: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def record(path: str, content: bytes, mtime: float | None = None) -> FileRecord:
    full = write_file(path, content)
    st = os.stat(full, follow_symlinks=False)
    return FileRecord(
        path=full,
        size=st.st_size,
        mtime=st.st_mtime,
        mtime_ns=st.st_mtime_ns,
        extension=os.path.splitext(full)[1].lower(),
    )


class TestA1HashTimeOfCheck:
    """A-1: the hashing open must verify post-open inode identity."""

    def test_inode_swap_between_stat_and_open_excludes_file(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        # Two real duplicate files with the same content.
        a = record(os.path.join(root, "a.bin"), b"duplicate-content")
        b = record(os.path.join(root, "b.bin"), b"duplicate-content")

        outcome = dd._hash_and_guard(a.path, a)
        assert outcome.reason == "hashed"

        # Simulate a swap-at-open: the OPEN HANDLE reports a different inode
        # identity than the pre-open stat vouched for (e.g. the path was
        # replaced between stat and open). The guarded open must refuse to hash.
        real_fstat = os.fstat

        def fake_fstat_swapped(fd):
            st = real_fstat(fd)
            return types.SimpleNamespace(
                st_dev=st.st_dev,
                st_ino=st.st_ino + 1,  # different file identity
                st_size=st.st_size,
            )

        monkeypatch.setattr(dd.os, "fstat", fake_fstat_swapped)
        outcome_swapped = dd._hash_and_guard(a.path, a)
        assert outcome_swapped.reason == "swapped_during_open"
        assert outcome_swapped.digest is None
        monkeypatch.undo()

        # The untouched file still hashes normally (the guard is per-open).
        outcome_ok = dd._hash_and_guard(b.path, b)
        assert outcome_ok.reason == "hashed"

        # Both verified members still form a real duplicate group.
        result = dd.detect_duplicates([a, b])
        assert result["duplicate_group_count"] == 1

    def test_normal_path_still_hashes(self, tmp_path):
        root = str(tmp_path)
        target = record(os.path.join(root, "plain.txt"), b"hello")
        outcome = dd._hash_and_guard(target.path, target)
        assert outcome.reason == "hashed"
        assert outcome.digest == dd.hashlib.sha256(b"hello").hexdigest()

    def test_no_group_without_hash_verification(self, tmp_path):
        """Detecting duplicates must always flow through _hash_and_guard; the
        detector never reports groups for size-identical but unverified files.
        """
        root = str(tmp_path)
        r1 = FileRecord(path=os.path.join(root, "gone1.txt"), size=4, mtime=0.0, mtime_ns=0, extension=".txt")
        r2 = FileRecord(path=os.path.join(root, "gone2.txt"), size=4, mtime=0.0, mtime_ns=0, extension=".txt")
        result = dd.detect_duplicates([r1, r2])
        assert result["duplicate_group_count"] == 0
        assert result["excluded_counts"].get("disappeared", 0) >= 1


class TestA2CandidateVerification:
    """A-2: missing players and directory candidates can never be eligible."""

    def test_missing_temp_candidate_not_eligible(self, tmp_path):
        root = str(tmp_path)
        finding = Finding(
            path=os.path.join(root, "vanished.tmp"),
            size=10,
            category=CATEGORY_TEMPORARY,
            reason="extension rule",
        )
        evaluation = evaluate_finding(finding, [root])
        assert evaluation.classification == CLASSIFICATION_POTENTIAL_CLEANUP  # rule matched
        assert evaluation.eligible is False
        assert "missing" in evaluation.eligibility_detail

    def test_directory_candidate_not_eligible(self, tmp_path):
        root = str(tmp_path)
        dir_named_tmp = os.path.join(root, "scratch.tmp")
        os.makedirs(dir_named_tmp)
        finding = Finding(path=dir_named_tmp, size=0, category=CATEGORY_TEMPORARY, reason="extension rule")
        evaluation = evaluate_finding(finding, [root])
        assert evaluation.classification == CLASSIFICATION_REVIEW_REQUIRED
        assert evaluation.eligible is False
        assert any("directory" in w.lower() for w in evaluation.warnings)

    def test_real_file_temp_candidate_eligible(self, tmp_path):
        root = str(tmp_path)
        target = write_file(os.path.join(root, "real.tmp"), b"x" * 10)
        finding = Finding(path=target, size=10, category=CATEGORY_TEMPORARY, reason="extension rule")
        evaluation = evaluate_finding(finding, [root])
        assert evaluation.classification == CLASSIFICATION_POTENTIAL_CLEANUP
        assert evaluation.eligible is True


class TestA3LocalHostHardening:
    """A-3: Host/Origin guard against rebinding and cross-site requests."""

    def test_foreign_host_rejected(self):
        response = client.get("/api/health", headers={"Host": "attacker.example.com"})
        assert response.status_code == 403

    def test_localhost_host_accepted(self):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_foreign_origin_rejected(self):
        response = client.post(
            "/api/scans",
            json={"roots": ["C:/definitely/not/real"]},
            headers={"Origin": "http://evil.example.com"},
        )
        assert response.status_code == 403

    def test_post_otherwise_still_validates(self):
        # Legitimate loopback origin reaches the endpoint and normal request
        # validation still applies (invalid root -> 422, foreign_host -> 403).
        response = client.post(
            "/api/scans",
            json={"roots": ["C:/definitely/not/real/xyzzy"]},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert response.status_code == 422


class TestA4RootCanonicalization:
    """A-4: approved roots are realpath-resolved before containment."""

    def test_trailing_slash_and_case_variants_contained(self, tmp_path):
        root = os.path.abspath(str(tmp_path))
        target = write_file(os.path.join(root, "nested", "f.tmp"), b"x")
        with_odd_form = root + os.sep
        violations = protection_violations(target, [with_odd_form])
        assert "outside_approved_roots" not in violations
        # Case-insensitive containment also holds (Windows-like matching even
        # off-Windows) thanks to normcase canonicalization.
        violations_case = protection_violations(target, [root.upper()])
        assert "outside_approved_roots" not in violations_case

    def test_path_similarity_is_not_containment(self, tmp_path):
        "A root E:\\data must not contain E:\\data2\\file.tmp"
        root = os.path.abspath(str(tmp_path))
        sibling = root + "2"
        target = write_file(os.path.join(sibling, "f.tmp"), b"x")
        violations = protection_violations(target, [root])
        assert "outside_approved_roots" in violations


class TestA5PartialAnalysis:
    """A-5: cancelled scans are explicitly marked partial in analysis API."""

    def test_completed_scan_not_partial(self, tmp_path):
        from app.api.scans import registry as app_registry

        with app_registry._lock:
            app_registry._scans.clear()
        write_file(os.path.join(str(tmp_path), "f.bin"), b"\0" * 10)
        scan_id = app_registry.start_scan([str(tmp_path)])
        import time as _time
        deadline = _time.time() + 10
        while _time.time() < deadline:
            if client.get(f"/api/scans/{scan_id}").json()["status"] == "completed":
                break
            _time.sleep(0.02)
        response = client.get(f"/api/scans/{scan_id}/analysis/large-files")
        assert response.status_code == 200
        assert response.json()["partial"] is False

    def test_cancelled_scan_marked_partial(self, tmp_path, monkeypatch):
        from app.api.scans import registry as app_registry
        from app.services.scanner import Scanner

        with app_registry._lock:
            app_registry._scans.clear()
        write_file(os.path.join(str(tmp_path), "f.bin"), b"\0" * 10)

        # Deterministically produce a cancelled scan.
        real_run = Scanner.run

        def cancelled_run(self):
            self.cancelled = True
            self._roll_up()
            return self

        monkeypatch.setattr(Scanner, "run", cancelled_run)
        scan_id = app_registry.start_scan([str(tmp_path)])
        import time as _time
        deadline = _time.time() + 10
        while _time.time() < deadline:
            if client.get(f"/api/scans/{scan_id}").json()["status"] == "cancelled":
                break
            _time.sleep(0.02)
        monkeypatch.setattr(Scanner, "run", real_run)

        for endpoint in ("large-files", "duplicates", "findings", "recommendations"):
            response = client.get(f"/api/scans/{scan_id}/analysis/{endpoint}")
            assert response.status_code == 200, endpoint
            assert response.json()["partial"] is True, endpoint
