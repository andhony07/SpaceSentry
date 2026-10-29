from __future__ import annotations

"""Analysis and cleanup services.

Phase 2 services are read-only (inspect + read file contents for hashing).
Phase 4 cleanup_executor performs user-approved quarantine/restore only, with
strict revalidation on every action.
"""
