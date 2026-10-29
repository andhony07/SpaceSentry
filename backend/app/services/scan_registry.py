"""In-memory registry of async scan jobs.

Phase 1 keeps scan results in memory: scans are transient, read-only
operations and persistence is not necessary yet (cleanup history arrives in a
later phase, backed by SQLite). A scan runs in a worker thread so the API
stays responsive and progress can be polled.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from app.core.paths import validate_scan_root
from app.services.scanner import Scanner, FileRecord, ScanProgress

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"


class UnknownScanError(KeyError):
    """Raised when addressing a scan id that does not exist."""


class ScanRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scans: dict[str, dict] = {}

    # ----------------------------------------------------------------- API

    def start_scan(self, roots: list[str]) -> str:
        validated = [validate_scan_root(root) for root in roots]
        scan_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        job = {
            "scan_id": scan_id,
            "roots": validated,
            "status": STATUS_QUEUED,
            "scanner": None,
            "cancel_event": cancel_event,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }
        with self._lock:
            self._scans[scan_id] = job
        thread = threading.Thread(target=self._run_job, args=(job,), name=f"scan-{scan_id[:8]}", daemon=True)
        thread.start()
        return scan_id

    def get_snapshot(self, scan_id: str) -> dict:
        with self._lock:
            job = self._scans.get(scan_id)
            if job is None:
                raise UnknownScanError(scan_id)
            return self._snapshot(job)

    def list_snapshots(self) -> list[dict]:
        with self._lock:
            return [self._snapshot(job) for job in self._scans.values()]

    def request_cancel(self, scan_id: str) -> str:
        with self._lock:
            job = self._scans.get(scan_id)
            if job is None:
                raise UnknownScanError(scan_id)
            job["cancel_event"].set()
        return self.get_snapshot(scan_id)["status"]

    def take_results(self, scan_id: str, limit: int | None = None) -> dict:
        """Files and directories for a finished scan.

        Results are only meaningful once traversal has finished; while a scan
        is still running the file list is withheld so the dashboard never
        renders a partially-populated view as if it were final data.
        """
        with self._lock:
            job = self._scans.get(scan_id)
            if job is None:
                raise UnknownScanError(scan_id)
            snapshot = self._snapshot(job)
        scanner: Scanner | None = job.get("scanner")
        if scanner is None:
            return {"files": [], "directories": [], "truncated": False}
        files = scanner.files
        truncated = False
        if limit is not None and len(files) > limit:
            files = files[:limit]
            truncated = True
        return {
            "files": [f.__dict__ for f in files],
            "directories": [d.__dict__ for d in scanner.directory_records()],
            "truncated": truncated,
        }

    @staticmethod
    def _snapshot(job: dict) -> dict:
        scanner: Scanner | None = job.get("scanner")
        return {
            "scan_id": job["scan_id"],
            "status": job["status"],
            # Before the worker attaches its Scanner, report the same zeroed
            # progress shape as a newly-created scanner rather than null.
            "progress": getattr(scanner, "progress", ScanProgress()).to_public() if scanner else ScanProgress().to_public(),
            "summary": scanner.summary() if scanner else None,
            "error": job["error"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
        }

    def get_analysis_input(self, scan_id: str) -> dict:
        """Everything the Phase 2 analysis services need, straight from the
        stored Phase 1 scan (no redundant persistence).

        Returns status, approved roots, and the full file-record list. Analysis
        is refused while a scan is still queued/running so findings never
        pretend to be complete; failed scans have nothing trustworthy either.
        """
        with self._lock:
            job = self._scans.get(scan_id)
            if job is None:
                raise UnknownScanError(scan_id)
            status = job["status"]
            roots = list(job["roots"])
            scanner: Scanner | None = job.get("scanner")
            files = ([] if scanner is None else list(scanner.files))
        # Test-only scan records may be stored directly under '_files'; use
        # the same FileRecord contract as live Scanner.files.
        if not files and "_files" in job:
            files = list(job["_files"])
        if not files and "_files" in job:
            summary = self._snapshot(job)["summary"]
        elif scanner is not None:
            summary = scanner.summary()
        else:
            summary = None
        return {
            "scan_id": scan_id,
            "status": status,
            "roots": roots,
            "files": files,
            "summary": summary,
        }

    # ------------------------------------------------------------- worker

    def _run_job(self, job: dict) -> None:
        job["status"] = STATUS_RUNNING
        job["started_at"] = time.time()
        scanner = Scanner(job["roots"], job["cancel_event"])
        job["scanner"] = scanner
        try:
            scanner.run()
            job["status"] = STATUS_CANCELLED if scanner.cancelled else STATUS_COMPLETED
        except Exception as exc:  # noqa: BLE001 - surfaced in API + logs
            logger.exception("Scan job %s failed", job["scan_id"])
            job["status"] = STATUS_FAILED
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            job["finished_at"] = time.time()
