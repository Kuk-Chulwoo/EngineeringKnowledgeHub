import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_path: Path
    storage_root: Path
    max_upload_bytes: int = 50 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        def resolve(name: str, default: str) -> Path:
            path = Path(os.getenv(name, default)).expanduser()
            return path if path.is_absolute() else PROJECT_ROOT / path

        limit = int(os.getenv("EKH_MAX_UPLOAD_MB", "50"))
        if limit < 1:
            raise ValueError("EKH_MAX_UPLOAD_MB must be positive")
        return cls(
            resolve("EKH_DATABASE_PATH", "data/hub.sqlite3"),
            resolve("EKH_STORAGE_ROOT", "data/datasheets"),
            limit * 1024 * 1024,
        )
