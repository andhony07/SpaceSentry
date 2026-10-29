#!/usr/bin/env python
"""Debug script: patch ScanRegistry and call cleanup preview endpoint."""
import sys, pathlib, uuid, time
sys.path.insert(0, 'backend')

import app.services.scan_registry as sr

def _patched(self, scan_id):
    with self._lock:
        job = self._scans.get(scan_id)
        if job is None:
            from app.services.scan_registry import UnknownScanError
            raise UnknownScanError(scan_id)
        status = job['status']
        roots = list(job['roots'])
        scanner = job.get('scanner')
        files = []
        if '_files' in job:
            files = list(job['_files'])
        elif scanner is not None:
            files = list(getattr(scanner, 'files', []))
        summary = self._snapshot(job)['summary']
    return {
        'scan_id': scan_id,
        'status': status,
        'roots': roots,
        'files': files,
        'summary': summary,
    }
sr.ScanRegistry.get_analysis_input = _patched

from fastapi.testclient import TestClient
from app.api.cleanup import router as cleanup_router
import fastapi
app = fastapi.FastAPI()
app.include_router(cleanup_router, prefix='/api')
c = TestClient(app, base_url='http://127.0.0.1')

with __import__('tempfile').TemporaryDirectory() as td:
    root = pathlib.Path(td) / 'root'
    root.mkdir()
    (root / 'a.tmp').write_text('aaa')
    
    reg = sr.ScanRegistry()
    scan_id = uuid.uuid4().hex
    stat = (root / 'a.tmp').stat()
    import app.services.scanner
    rec = app.services.scanner.FileRecord(path=str(root / 'a.tmp'), size=3, mtime=stat.st_mtime, mtime_ns=int(stat.st_mtime_ns), extension='.tmp')
    reg._scans[scan_id] = {
        'scan_id': scan_id,
        'roots': [str(root.resolve())],
        'status': 'completed',
        'scanner': None,
        'cancel_event': None,
        'error': None,
        'started_at': time.time() - 1,
        'finished_at': time.time(),
        '_files': [rec],
    }
    r = c.post(
        '/api/cleanup/preview',
        json={'scan_id': scan_id, 'candidate_ids': [str(root / 'a.tmp')]},
    )
    print('STATUS:', r.status_code)
    print('TEXT:', r.text)
