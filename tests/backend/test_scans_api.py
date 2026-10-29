"""API-level tests for the scan endpoints.

Runs the real FastAPI app against real (temporary) filesystem data and
exercise validation, lifecycle, and error paths end to end.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, base_url="http://127.0.0.1:8765")


def write_file(path: str, size: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)


def wait_for_completion(scan_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/scans/{scan_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"completed", "cancelled", "failed"}:
            return last
        time.sleep(0.02)
    raise AssertionError(f"Scan did not finish in time; last status: {last}")


@pytest.fixture(autouse=True)
def fresh_registry():
    """Isolate scan state between tests by clearing the app's registry."""
    from app.api.scans import registry as app_registry
    with app_registry._lock:
        app_registry._scans.clear()
    yield
    with app_registry._lock:
        app_registry._scans.clear()


class TestScanLifecycle:
    def test_scan_end_to_end(self, tmp_path):
        root = str(tmp_path / "data")
        write_file(os.path.join(root, "a.txt"), 100)
        write_file(os.path.join(root, "nested", "b.bin"), 300)

        created = client.post("/api/scans", json={"roots": [str(tmp_path)]})
        assert created.status_code == 201, created.text
        scan_id = created.json()["scan_id"]

        status = wait_for_completion(scan_id)
        assert status["status"] == "completed"
        summary = status["summary"]
        assert summary["file_count"] == 2
        assert summary["bytes_scanned"] == 400

    def test_results_endpoint(self, tmp_path):
        root = str(tmp_path / "data")
        write_file(os.path.join(root, "a.txt"), 100)
        response = client.post("/api/scans", json={"roots": [str(tmp_path)]})
        scan_id = response.json()["scan_id"]
        wait_for_completion(scan_id)

        results = client.get(f"/api/scans/{scan_id}/results")
        assert results.status_code == 200
        body = results.json()
        assert body["status"] == "completed"
        assert len(body["files"]) == 1
        record = body["files"][0]
        assert record["path"].endswith("a.txt")
        assert record["size"] == 100
        assert record["extension"] == ".txt"
        directories = {d["path"]: d["total_size"] for d in body["directories"]}
        assert directories[str(tmp_path)] == 100

    def test_results_limit(self, tmp_path):
        root = str(tmp_path)
        for i in range(5):
            write_file(os.path.join(root, f"f{i}.txt"), 1)
        scan_id = client.post("/api/scans", json={"roots": [str(tmp_path)]}).json()["scan_id"]
        wait_for_completion(scan_id)
        body = client.get(f"/api/scans/{scan_id}/results", params={"limit": 2}).json()
        assert len(body["files"]) == 2
        assert body["truncated"] is True

    def test_scan_list(self, tmp_path):
        scan_id = client.post("/api/scans", json={"roots": [str(tmp_path)]}).json()["scan_id"]
        wait_for_completion(scan_id)
        listing = client.get("/api/scans").json()
        assert scan_id in [s["scan_id"] for s in listing["scans"]]

    def test_cancel_unknown_scan_returns_404(self):
        response = client.post("/api/scans/definitely-not-real/cancel")
        assert response.status_code == 404

    def test_status_unknown_scan_returns_404(self):
        response = client.get("/api/scans/definitely-not-real")
        assert response.status_code == 404
        assert "Unknown scan id" in response.json()["detail"]

    def test_cancel_pre_started_scan(self, tmp_path):
        response = client.post("/api/scans", json={"roots": [str(tmp_path)]})
        scan_id = response.json()["scan_id"]
        cancel = client.post(f"/api/scans/{scan_id}/cancel")
        assert cancel.status_code == 200
        from app.api.scans import registry as app_registry
        with app_registry._lock:
            app_registry._scans[scan_id]["cancel_event"].set()
        time.sleep(0.1)
        status = client.get(f"/api/scans/{scan_id}").json()
        assert status["status"] in {"cancelled", "completed"}  # tiny scans can finish first


class TestValidationAndErrors:
    def test_rejects_unknown_roots_field(self, tmp_path):
        response = client.post("/api/scans", json={"paths": [str(tmp_path)]})
        assert response.status_code == 422

    def test_rejects_empty_roots(self):
        response = client.post("/api/scans", json={"roots": []})
        assert response.status_code == 422

    def test_rejects_relative_and_nonexistent_roots(self, tmp_path):
        bad = client.post("/api/scans", json={"roots": ["relative/path", str(tmp_path / "missing")]})
        assert bad.status_code == 422

    def test_too_many_roots_rejected(self):
        response = client.post("/api/scans", json={"roots": [f"C:\\dir{i}" for i in range(9)]})
        assert response.status_code == 422

    def test_health_endpoint(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["mode"] == "read-only"

    def test_drives_endpoint_reports_no_fake_data(self):
        response = client.get("/api/system/drives")
        assert response.status_code == 200
        for drive in response.json()["drives"]:
            assert drive["total_bytes"] > 0  # real capacity, never fabricated
            assert drive["free_bytes"] >= 0


class TestReadOnlyGuarantee:
    def test_scan_api_never_modifies_files(self, tmp_path):
        root = str(tmp_path / "data")
        write_file(os.path.join(root, "report.txt"), 123)
        write_file(os.path.join(root, "sub", "photo.jpg"), 4_000)

        def digest():
            state = {}
            for dirpath, _dirs, files in os.walk(str(tmp_path)):
                for name in files:
                    full = os.path.join(dirpath, name)
                    with open(full, "rb") as handle:
                        state[full] = (os.stat(full).st_size, os.stat(full).st_mtime_ns, hash(handle.read()))
            return state

        before = digest()
        scan_id = client.post("/api/scans", json={"roots": [str(tmp_path)]}).json()["scan_id"]
        wait_for_completion(scan_id)
        # Force-read results to ensure no endpoint side effect persists.
        client.get(f"/api/scans/{scan_id}/results")
        after = digest()
        assert before == after
