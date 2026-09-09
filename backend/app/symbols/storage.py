import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

MAX_SYMBOL_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class StoredSymbol:
    key: str
    size: int
    sha256: str


class SymbolStorage:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        match = re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)/([0-9a-f]{32}\.c)", key)
        if not match:
            raise ValueError("Invalid symbol storage key")
        return self.root.joinpath(*match.groups())

    def put(self, component_id: int, symbol_id: int, source: BinaryIO) -> StoredSymbol:
        key = f"{component_id}/{symbol_id}/{uuid4().hex}.c"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        try:
            with path.open("xb") as destination:
                while chunk := source.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_SYMBOL_BYTES:
                        raise ValueError("Symbol file exceeds 2 MiB")
                    digest.update(chunk)
                    destination.write(chunk)
            if size == 0:
                raise ValueError("Symbol file is empty")
            return StoredSymbol(key, size, digest.hexdigest())
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
            path.parent.parent.rmdir()
        except OSError:
            pass
