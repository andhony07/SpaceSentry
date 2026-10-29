"""Application configuration for the SpaceSentry backend.

The API is intentionally localhost-only. Cleanup endpoints must never be
reachable from other machines, so host binding and the CORS allowlist are
the first line of defense and are loaded from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        raw_origins = env.get("SPACESSENTRY_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
        origins = tuple(o.strip() for o in raw_origins.split(",") if o.strip())
        return cls(
            host=env.get("SPACESSENTRY_HOST", DEFAULT_HOST),
            port=int(env.get("SPACESSENTRY_PORT", str(DEFAULT_PORT))),
            allowed_origins=origins or (DEFAULT_ALLOWED_ORIGINS,),
        )


def get_settings() -> Settings:
    return Settings.from_env()
