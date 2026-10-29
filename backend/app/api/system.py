"""System-level read-only endpoints: available fixed/removable drives.

The dashboard needs real capacity values; Windows reports these per-volume
via GetDiskFreeSpaceExW. Uses ctypes against system APIs — no shell out, no
third-party dependency, no modification of anything.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from fastapi import APIRouter

from app.schemas.scan import DriveInfoModel, DrivesResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

_DRIVE_TYPE_NAMES = {
    0: "unknown",
    1: "no_root",
    2: "removable",
    3: "fixed",
    4: "network",
    5: "cdrom",
    6: "ramdisk",
}
_RELEVANT_TYPES = {"fixed", "removable"}


def _windows_drive_infos() -> list[DriveInfoModel]:
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows only
    buf = ctypes.create_unicode_buffer(512)
    length = kernel32.GetLogicalDriveStringsW(512, buf)
    if length == 0 or length > 512:
        logger.warning("GetLogicalDriveStringsW failed or unexpected size (%s)", length)
        return []
    letters = [chunk for chunk in buf.value.split("\x00") if chunk]
    drives: list[DriveInfoModel] = []
    for letter in letters:
        letter = letter.strip()
        if not letter:
            continue
        kind = _DRIVE_TYPE_NAMES.get(kernel32.GetDriveTypeW(ctypes.c_wchar_p(letter)), "unknown")
        if kind not in _RELEVANT_TYPES:
            continue
        total = ctypes.c_ulonglong(0)
        free = ctypes.c_ulonglong(0)
        if kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(letter),
            ctypes.byref(ctypes.c_ulonglong(0)),
            ctypes.byref(total),
            ctypes.byref(free),
        ):
            drives.append(
                DriveInfoModel(
                    drive=letter.rstrip("\\") or letter,
                    drive_type=kind,
                    total_bytes=total.value,
                    free_bytes=free.value,
                )
            )
        else:
            logger.debug("Drive %s reports no capacity (not ready) — skipped", letter)
    return drives


@router.get("/system/drives", response_model=DrivesResponse)
def list_drives() -> DrivesResponse:
    if sys.platform == "win32":
        drives = _windows_drive_infos()
    else:  # No capacity data without platform APIs; report none rather than fabricate.
        logger.info("Drive capacity reporting is Windows-only in Phase 1.")
        drives = []
    return DrivesResponse(drives=drives)
