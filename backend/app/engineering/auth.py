"""One trusted local reviewer; passwords never travel to extraction workers."""

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from ..services import ServiceError

ALLOWED_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}


def password_record(name: str, password: str) -> dict[str, str]:
    if len(password) < 12 or not name.strip():
        raise ValueError("Use a reviewer name and a password of at least 12 characters")
    salt = secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return {"name": name.strip(), "salt": salt, "password_hash": derived.hex()}


@dataclass
class Session:
    actor: str
    csrf: str
    expires: float


class LocalReviewer:
    def __init__(self, path: Path | None):
        self.path = path
        self.sessions: dict[str, Session] = {}
        self.failures: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()

    @staticmethod
    def origin(request: Request) -> None:
        if request.headers.get("origin") not in ALLOWED_ORIGINS:
            raise ServiceError(403, "Local trusted Origin header required")

    def login(self, request: Request, name: str, password: str) -> tuple[str, Session]:
        self.origin(request)
        if self.path is None or not self.path.is_file():
            raise ServiceError(503, "Configure the local reviewer with scripts/setup-reviewer.ps1")
        peer = request.client.host if request.client else "local"
        with self.lock:
            now = time.monotonic()
            count, until = self.failures.get(peer, (0, 0))
            if count >= 5 and now < until:
                raise ServiceError(429, "Too many attempts; try again in one minute")
            record = json.loads(self.path.read_text(encoding="utf-8"))
            actual = hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(record["salt"]), n=16384, r=8, p=1
            ).hex()
            if not (
                hmac.compare_digest(actual, record["password_hash"])
                and hmac.compare_digest(name.encode(), record["name"].encode())
            ):
                self.failures[peer] = ((count + 1) if now < until else 1, now + 60)
                raise ServiceError(401, "Invalid reviewer credentials")
            self.failures.pop(peer, None)
            self.sessions = {k: v for k, v in self.sessions.items() if v.expires > now}
            if len(self.sessions) >= 128:
                raise ServiceError(429, "Session limit reached")
            token = secrets.token_urlsafe(32)
            session = Session(record["name"], secrets.token_urlsafe(32), now + 8 * 3600)
            self.sessions[token] = session
            return token, session

    def authenticate(self, request: Request, mutation: bool = True) -> Session:
        with self.lock:
            token = request.cookies.get("ekh_reviewer", "")
            session = self.sessions.get(token)
            if session is None or session.expires <= time.monotonic():
                self.sessions.pop(token, None)
                raise ServiceError(401, "Reviewer sign-in required")
            if mutation:
                self.origin(request)
                if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
                    raise ServiceError(403, "Invalid CSRF token")
            return session

    def logout(self, request: Request) -> None:
        self.authenticate(request)
        with self.lock:
            self.sessions.pop(request.cookies.get("ekh_reviewer", ""), None)
