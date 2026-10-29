"""Phase 4 cleanup API tests using synthetic files in temporary directories."""
from __future__ import annotations

import os
import pathlib
import tempfile
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cleanup import router as cleanup_router, _set_runtime_registry
from app.services.cleanup_executor import CleanupOperationRegistry
from app.services.scan_registry import ScanRegistry
from app.services.scanner import FileRecord, ScanProgress


class _FakeScanner:
    def __init__(self, files):
        self.files = files
        self.progress = ScanProgress(files_scanned=len(files), bytes_scanned=sum(f.size for f in files))

    def directory_records(self):
        return []

    def summary(self):
        return {"file_count": len(self.files), "bytes_scanned": sum(f.size for f in self.files), "root_errors": []}


def _register_scan(registry: ScanRegistry, scan_id: str, roots: list[str], files: list[FileRecord], status="completed"):
    registry._scans[scan_id] = {
        "scan_id": scan_id, "roots": roots, "status": status, "scanner": _FakeScanner(files),
        "cancel_event": None, "error": None, "started_at": time.time() - 1, "finished_at": time.time(),
    }


def _record(path: pathlib.Path) -> FileRecord:
    st = path.stat()
    return FileRecord(str(path), st.st_size, st.st_mtime, path.suffix, st.st_mtime_ns, "ok")


def _scan_for(root: pathlib.Path, paths: list[pathlib.Path], *, status="completed"):
    registry = ScanRegistry()
    scan_id = uuid.uuid4().hex
    _register_scan(registry, scan_id, [str(root.resolve())], [_record(path) for path in paths], status)
    return scan_id, registry


def _client(registry: ScanRegistry, expiry_seconds: float | None = None, quarantine_root: pathlib.Path | None = None):
    app = FastAPI()
    app.state.scan_registry = registry
    app.include_router(cleanup_router, prefix="/api")
    _set_runtime_registry(CleanupOperationRegistry(quarantine_root, expiry_seconds=expiry_seconds))
    return TestClient(app, base_url="http://127.0.0.1")


def _preview(client: TestClient, scan_id: str, paths: list[pathlib.Path]):
    response = client.post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(p) for p in paths]})
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client: TestClient, preview: dict):
    response = client.post("/api/cleanup/approve", json={"operation_id": preview["operation_id"], "session_token": preview["session_token"]})
    assert response.status_code == 201, response.text
    return response


def _quarantine(client: TestClient, preview: dict, candidate_id: str):
    return client.post("/api/cleanup/quarantine", json={
        "operation_id": preview["operation_id"], "session_token": preview["session_token"], "candidate_id": candidate_id,
    })


class TestCleanupPreviewAccepted:
    def test_preview_returns_operation_and_can_quarantine_items(self, tmp_path):
        root = tmp_path / "root"; root.mkdir()
        paths = [root / "a.tmp", root / "b.tmp"]
        for p in paths: p.write_text("aaa")
        scan_id, registry = _scan_for(root, paths)
        body = _preview(_client(registry), scan_id, paths)
        assert body["status"] == "pending" and body["session_token"] and len(body["items"]) == 2
        assert all(item["can_quarantine"] and not item["revalidation_errors"] for item in body["items"])

    def test_preview_binds_session_token_on_approve(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry)
        preview = _preview(client, scan_id, [path])
        approved = _approve(client, preview)
        assert approved.json()["status"] == "approved"


class TestCleanupPreviewRejectsNonEligible:
    def test_rejects_unknown_candidate_ids(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path])
        response = _client(registry).post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": ["not-a-record"]})
        assert response.status_code == 422

    def test_rejects_when_no_eligible_candidates(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "keep.txt"; path.write_text("important")
        scan_id, registry = _scan_for(root, [path])
        response = _client(registry).post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(path)]})
        assert response.status_code == 422


class TestCleanupPreviewRejectsBadScans:
    def test_rejects_unknown_scan_id(self):
        response = _client(ScanRegistry()).post("/api/cleanup/preview", json={"scan_id": "missing", "candidate_ids": ["x"]})
        assert response.status_code == 404

    def test_rejects_scan_still_running(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); registry = ScanRegistry(); scan_id = uuid.uuid4().hex
        _register_scan(registry, scan_id, [str(root)], [], status="running")
        response = _client(registry).post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": ["x"]})
        assert response.status_code == 409


class TestCleanupQuarantineExecutes:
    def test_quarantine_moves_file_to_dedicated_op_dir(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); quarantine = tmp_path / "quarantine"; path = root / "a.tmp"; path.write_text("hello")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry, quarantine_root=quarantine)
        preview = _preview(client, scan_id, [path]); _approve(client, preview)
        response = _quarantine(client, preview, str(path)); assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["status"] == "ok" and result["bytes_moved_to_quarantine"] == 5
        assert result["bytes_reclaimed"] >= 0 and not path.exists() and pathlib.Path(result["quarantine_path"]).exists()

    def test_quarantine_rejects_if_source_changed_before_exec(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry)
        preview = _preview(client, scan_id, [path]); _approve(client, preview); path.write_text("changed-size")
        response = _quarantine(client, preview, str(path)); assert response.status_code == 200
        assert response.json()["result"]["status"] == "failed" and path.exists()

    def test_quarantine_collision_fails_without_overwrite(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); qroot = tmp_path / "q"; path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry, quarantine_root=qroot)
        preview = _preview(client, scan_id, [path]); _approve(client, preview)
        from app.services.cleanup_executor import _safe_quarantine_name
        record = _record(path); opdir = qroot / preview["operation_id"]
        collision = opdir / _safe_quarantine_name(record, 0); collision.write_text("preserve")
        response = _quarantine(client, preview, str(path)); assert response.status_code == 200
        assert response.json()["result"]["status"] == "failed" and collision.read_text() == "preserve" and path.exists()


class TestCleanupRestoreRefusesOverwrite:
    def test_restore_refuses_when_destination_exists(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "del.tmp"; path.write_text("del")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry)
        preview = _preview(client, scan_id, [path]); _approve(client, preview); assert _quarantine(client, preview, str(path)).status_code == 200
        target = root / "original.txt"; target.write_text("keep")
        response = client.post("/api/cleanup/restore", json={"operation_id": preview["operation_id"], "session_token": preview["session_token"], "candidate_id": str(path), "target_path": str(target)})
        assert response.status_code == 200 and response.json()["result"]["status"] == "failed" and target.read_text() == "keep"

    def test_restores_completed_quarantine(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("restore me")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry)
        preview = _preview(client, scan_id, [path]); _approve(client, preview); moved = _quarantine(client, preview, str(path)).json()["result"]
        response = client.post("/api/cleanup/restore", json={"operation_id": preview["operation_id"], "session_token": preview["session_token"], "candidate_id": str(path), "target_path": str(path)})
        assert response.status_code == 200 and response.json()["result"]["status"] == "ok" and path.read_text() == "restore me"


class TestCleanupAuthorization:
    def test_rejects_wrong_session_token(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry); preview = _preview(client, scan_id, [path])
        response = client.post("/api/cleanup/approve", json={"operation_id": preview["operation_id"], "session_token": "wrong"})
        assert response.status_code == 403

    def test_rejects_expired_token_after_time_passes(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry, expiry_seconds=0.001); preview = _preview(client, scan_id, [path])
        time.sleep(0.01)
        response = client.post("/api/cleanup/approve", json={"operation_id": preview["operation_id"], "session_token": preview["session_token"]})
        assert response.status_code == 410


class TestCleanupLockingAndStatus:
    def test_duplicate_quarantine_rejected(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry); preview = _preview(client, scan_id, [path]); _approve(client, preview)
        assert _quarantine(client, preview, str(path)).status_code == 200
        duplicate = _quarantine(client, preview, str(path))
        assert duplicate.status_code == 409 and duplicate.json()["detail"].startswith("already processed")


class TestCleanupAuditAndList:
    def test_list_operations_and_audit(self, tmp_path):
        root = tmp_path / "root"; root.mkdir(); path = root / "a.tmp"; path.write_text("aaa")
        scan_id, registry = _scan_for(root, [path]); client = _client(registry); preview = _preview(client, scan_id, [path]); _approve(client, preview)
        quarantine = _quarantine(client, preview, str(path)); assert quarantine.status_code == 200
        audit = client.get(f"/api/cleanup/operations/{preview['operation_id']}/audit", params={"session_token": preview["session_token"]})
        assert audit.status_code == 200 and [r["action"] for r in audit.json()["rows"]].count("preview") == 1
        assert [r["action"] for r in audit.json()["rows"]].count("quarantine") == 1
        listing = client.get("/api/cleanup/operations")
        assert listing.status_code == 200 and any(o["operation_id"] == preview["operation_id"] for o in listing.json()["operations"])
        assert quarantine.json()["result"]["bytes_reclaimed"] >= 0
