import pathlib

p = pathlib.Path("tests/backend/test_cleanup_api.py")
src = p.read_text()

tail = """

class TestCleanupRestoreRefusesOverwrite:
    def test_restore_refuses_when_destination_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "root"
            root.mkdir()
            src = root / "del.tmp"
            dst = root / "original.txt"
            dst.write_text("kept")
            src.write_text("del")
            scan_id, _ = _scan_id_for_files([str(root.resolve())], [src])
            c = _client()
            pr = c.post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(src)]})
            assert pr.status_code == 201
            op_id = pr.json()["operation_id"]
            token = pr.json()["session_token"]
            c.post("/api/cleanup/approve", json={"operation_id": op_id, "session_token": token})
            qr = c.post("/api/cleanup/quarantine", json={"operation_id": op_id, "session_token": token, "candidate_id": str(src)})
            assert qr.status_code == 200, qr.text
            rr = c.post("/api/cleanup/restore", json={"operation_id": op_id, "session_token": token, "candidate_id": str(src), "target_path": str(dst)})
            assert rr.status_code == 200, rr.text
            assert rr.json()["result"]["status"] == "failed"
            assert rr.json()["result"].get("failure_reason", "").startswith("destination already exists")


class TestCleanupAuthorization:
    def test_rejects_wrong_session_token(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "root"
            root.mkdir()
            (root / "a.tmp").write_text("aaa")
            scan_id, _ = _scan_id_for_files([str(root.resolve())], [root / "a.tmp"])
            c = _client()
            pr = c.post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(root / "a.tmp")]})
            assert pr.status_code == 201
            op_id = pr.json()["operation_id"]
            r = c.post("/api/cleanup/approve", json={"operation_id": op_id, "session_token": "wrong-token"})
            assert r.status_code == 403, r.text

    def test_rejects_expired_token_after_time_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "root"
            root.mkdir()
            (root / "a.tmp").write_text("aaa")
            scan_id, _ = _scan_id_for_files([str(root.resolve())], [root / "a.tmp"])
            c = _client()
            pr = c.post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(root / "a.tmp")]})
            assert pr.status_code == 201
            op_id = pr.json()["operation_id"]
            token = pr.json()["session_token"]
            time.sleep(0.01)
            r = c.post("/api/cleanup/approve", json={"operation_id": op_id, "session_token": token})
            assert r.status_code in (403, 404, 409, 410), r.text
            if r.status_code == 409:
                assert r.json()["detail"].startswith("Operation already approved")


class TestCleanupLockingAndStatus:
    def test_duplicate_quarantine_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "root"
            root.mkdir()
            src = root / "a.tmp"
            src.write_text("aaa")
            scan_id, _ = _scan_id_for_files([str(root.resolve())], [src])
            c = _client()
            pr = c.post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(src)]})
            assert pr.status_code == 201
            op_id = pr.json()["operation_id"]
            token = pr.json()["session_token"]
            c.post("/api/cleanup/approve", json={"operation_id": op_id, "session_token": token})
            c.post("/api/cleanup/quarantine", json={"operation_id": op_id, "session_token": token, "candidate_id": str(src)})
            dup = c.post("/api/cleanup/quarantine", json={"operation_id": op_id, "session_token": token, "candidate_id": str(src)})
            assert dup.status_code == 409, dup.text
            assert dup.json()["detail"].startswith("already processed")


class TestCleanupAuditAndList:
    def test_list_operations_and_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "root"
            root.mkdir()
            src = root / "a.tmp"
            src.write_text("aaa")
            scan_id, _ = _scan_id_for_files([str(root.resolve())], [src])
            c = _client()
            pr = c.post("/api/cleanup/preview", json={"scan_id": scan_id, "candidate_ids": [str(src)]})
            assert pr.status_code == 201
            op_id = pr.json()["operation_id"]
            token = pr.json()["session_token"]
            c.post("/api/cleanup/approve", json={"operation_id": op_id, "session_token": token})
            qr = c.post("/api/cleanup/quarantine", json={"operation_id": op_id, "session_token": token, "candidate_id": str(src)})
            assert qr.status_code == 200, qr.text
            lr = c.get(f"/api/cleanup/operations/{op_id}/audit", params={"session_token": token})
            assert lr.status_code == 200, lr.text
            body = lr.json()
            assert body["operation_id"] == op_id
            assert len(body["rows"]) >= 2
            r = c.get("/api/cleanup/operations", params={"session_token": token})
            assert r.status_code == 200, r.text
            ops = r.json()["operations"]
            assert any(o["operation_id"] == op_id for o in ops)
"""
p.write_text(p.read_text() + tail)
print("ok", len(p.read_text()))
