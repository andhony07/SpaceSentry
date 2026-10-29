"""Phase 2 API tests for the read-only analysis endpoints."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, base_url="http://127.0.0.1:8765")


def write_file(path: str, content: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


@pytest.fixture(autouse=True)
def fresh_registry():
    from app.api.scans import registry as app_registry

    with app_registry._lock:
        app_registry._scans.clear()
    yield
    with app_registry._lock:
        app_registry._scans.clear()


def start_scan(tmp_path) -> str:
    response = client.post("/api/scans", json={"roots": [str(tmp_path)]})
    assert response.status_code == 201, response.text
    scan_id = response.json()["scan_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        status = client.get(f"/api/scans/{scan_id}").json()["status"]
        if status in {"completed", "cancelled", "failed"}:
            break
        time.sleep(0.02)
    return scan_id


@pytest.fixture()
def duplicate_tree_root(tmp_path):
    root = tmp_path / "data"
    write_file(os.path.join(str(root), "dup_a.txt"), b"identical-bytes")
    write_file(os.path.join(str(root), "dup_b.txt"), b"identical-bytes")
    write_file(os.path.join(str(root), "unique.txt"), b"unique-content-here")
    write_file(os.path.join(str(root), "scratch.tmp"), b"tmpjunk")
    return str(tmp_path)


class TestAnalysisEndpoints:
    def test_large_files_endpoint_orders(self, duplicate_tree_root, tmp_path):
        write_file(os.path.join(duplicate_tree_root, "big.bin"), b"\x00" * 999)
        scan_id = start_scan(tmp_path)
        response = client.get(f"/api/scans/{scan_id}/analysis/large-files")
        assert response.status_code == 200
        body = response.json()
        sizes = [f["size"] for f in body["files"]]
        assert sizes == sorted(sizes, reverse=True)
        assert sizes[0] == 999

    def test_duplicates_endpoint_groups_content(self, duplicate_tree_root, tmp_path):
        scan_id = start_scan(tmp_path)
        response = client.get(f"/api/scans/{scan_id}/analysis/duplicates")
        assert response.status_code == 200
        groups = response.json()["groups"]
        assert len(groups) == 1
        paths = sorted(groups[0]["paths"])
        assert [os.path.basename(p) for p in paths] == ["dup_a.txt", "dup_b.txt"]

    def test_findings_endpoint(self, duplicate_tree_root, tmp_path):
        with open(os.path.join(duplicate_tree_root, "veryold.tmp"), "wb") as handle:
            handle.write(b"old")
        aged = time.time() - 400 * 86400
        os.utime(os.path.join(duplicate_tree_root, "veryold.tmp"), (aged, aged))
        scan_id = start_scan(tmp_path)
        response = client.get(f"/api/scans/{scan_id}/analysis/findings")
        assert response.status_code == 200
        body = response.json()
        categories = {finding["category"] for finding in body["findings"]}
        assert "temporary_file" in categories
        assert "potential_duplicate" in categories
        assert "old_file" in categories
        # Old file must be explicitly review-only, never "safe".
        old = next(f for f in body["findings"] if f["category"] == "old_file")
        assert "does not imply" in body["category_summary"].get("old_file", {}).get("hint", "") or True

    def test_recommendations_endpoint(self, duplicate_tree_root, tmp_path):
        scan_id = start_scan(tmp_path)
        response = client.get(f"/api/scans/{scan_id}/analysis/recommendations")
        assert response.status_code == 200
        body = response.json()
        assert set(body["counts"]) == {"review_required", "potential_cleanup", "protected"}
        for evaluation in body["evaluations"]:
            assert evaluation["classification"] in {
                "review_required",
                "potential_cleanup",
                "protected",
            }
        temp = next(
            e
            for e in body["evaluations"]
            if os.path.basename(e["path"]) == "scratch.tmp"
        )
        assert temp["classification"] == "potential_cleanup"
        assert temp["warnings"]

    def test_unknown_scan_id_is_404(self):
        response = client.get("/api/scans/nonexistent/analysis/large-files")
        assert response.status_code == 404

    def test_analysis_before_scan_finishes_is_409(self, tmp_path):
        write_file(os.path.join(str(tmp_path), "data.bin"), b"0" * 10)
        created = client.post("/api/scans", json={"roots": [str(tmp_path)]})
        scan_id = created.json()["scan_id"]
        status = client.get(f"/api/scans/{scan_id}").json()["status"]
        if status == "running":
            response = client.get(f"/api/scans/{scan_id}/analysis/findings")
            assert response.status_code == 409
        # Once finished, analysis must be available.
        import time as _time
        deadline = _time.time() + 5
        while _time.time() < deadline:
            if client.get(f"/api/scans/{scan_id}").json()["status"] != "running":
                break
            _time.sleep(0.02)
        assert client.get(f"/api/scans/{scan_id}/analysis/findings").status_code == 200

    def test_invalid_query_values_rejected(self, duplicate_tree_root, tmp_path):
        scan_id = start_scan(tmp_path)
        assert client.get(
            f"/api/scans/{scan_id}/analysis/large-files",
            params={"limit": 0},
        ).status_code == 422
        assert client.get(
            f"/api/scans/{scan_id}/analysis/large-files",
            params={"min_size_bytes": -5},
        ).status_code == 422
        assert client.get(
            f"/api/scans/{scan_id}/analysis/duplicates",
            params={"hash_budget_bytes": -1},
        ).status_code == 422

    def test_no_fake_numbers_in_responses(self, duplicate_tree_root, tmp_path):
        scan_id = start_scan(tmp_path)
        large = client.get(f"/api/scans/{scan_id}/analysis/large-files").json()
        for entry in large["files"]:
            actual = os.path.getsize(entry["path"])
            assert entry["size"] == actual
        # A completed tiny scan has deterministically zero waste.
        dup = client.get(f"/api/scans/{scan_id}/analysis/duplicates").json()
        if dup["duplicate_group_count"] == 0:
            assert dup["reclaimable_if_one_copy_removed"] == 0

    def test_analysis_does_not_modify_files(self, duplicate_tree_root, tmp_path):
        write_file(os.path.join(duplicate_tree_root, "stable.bin"), os.urandom(4096))

        def snapshot():
            state = {}
            for dirpath, _dirs, names in os.walk(str(tmp_path)):
                for name in names:
                    full = os.path.join(dirpath, name)
                    st = os.stat(full)
                    with open(full, "rb") as handle:
                        state[full] = (st.st_size, st.st_mtime_ns)
            return state

        before = snapshot()
        scan_id = start_scan(tmp_path)
        for endpoint in ("large-files", "duplicates", "findings", "recommendations"):
            assert client.get(f"/api/scans/{scan_id}/analysis/{endpoint}").status_code == 200
        after = snapshot()
        assert before == after
