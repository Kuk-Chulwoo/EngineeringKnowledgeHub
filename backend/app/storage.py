import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4


class UploadTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int
    sha256: str


class Storage(Protocol):
    def put(self, source: BinaryIO, max_bytes: int) -> StoredFile: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}\.pdf", key):
            raise ValueError("Invalid storage key")
        return self.root / key

    def put(self, source: BinaryIO, max_bytes: int) -> StoredFile:
        self.root.mkdir(parents=True, exist_ok=True)
        key = f"{uuid4().hex}.pdf"
        path = self._path(key)
        size = 0
        digest = hashlib.sha256()
        try:
            with path.open("xb") as destination:
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise UploadTooLarge("PDF exceeds configured upload limit")
                    digest.update(chunk)
                    destination.write(chunk)
            return StoredFile(key, size, digest.hexdigest())
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
