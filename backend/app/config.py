"""Runtime configuration, read from the environment (or a .env file)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GCG_",
                                      extra="ignore")

    app_name: str = "Gridfinity Cutout Generator"
    data_dir: Path = Path("/var/lib/gridfinity-cutout")
    database_url: str = ""

    secret_key: str = ""
    token_ttl_hours: int = 24 * 14
    allow_registration: bool = True

    max_upload_mb: int = 40
    max_scan_images: int = 200

    # background worker
    worker_poll_seconds: float = 1.0
    scan_voxel_mm: float = 0.5
    scan_max_height_mm: float = 120.0
    scan_extent_mm: float = 160.0

    preview_cache_size: int = 24
    segmentation_model: str = "u2net"
    cors_origins: str = ""

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def scans_dir(self) -> Path:
        return self.data_dir / "scans"

    @property
    def meshes_dir(self) -> Path:
        return self.data_dir / "meshes"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.images_dir, self.scans_dir,
                     self.meshes_dir, self.models_dir):
            path.mkdir(parents=True, exist_ok=True)

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'app.db'}"

    def resolved_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        # Persist a generated key so that sessions survive a restart even when
        # the operator never set one.
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_text().strip()
        self.ensure_dirs()
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated)
        key_file.chmod(0o600)
        return generated


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
