"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/geo.db")
    )
    # Hard cap on the size of the uploaded file itself.
    max_upload_bytes: int = field(
        default_factory=lambda: _int_env("MAX_UPLOAD_MB", 50) * 1024 * 1024
    )
    # Zip-bomb protection: cap on the total size after extraction.
    max_uncompressed_bytes: int = field(
        default_factory=lambda: _int_env("MAX_UNCOMPRESSED_MB", 200) * 1024 * 1024
    )
    max_zip_members: int = field(default_factory=lambda: _int_env("MAX_ZIP_MEMBERS", 200))


def get_settings() -> Settings:
    return Settings()
