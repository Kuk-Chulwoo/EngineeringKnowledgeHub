"""Exercise a real Uvicorn process using isolated temporary runtime data."""

import io
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def server(tmp_path: Path) -> Iterator[httpx.Client]:
    environment = {
        **os.environ,
        "EKH_DATABASE_PATH": str(tmp_path / "live.sqlite3"),
        "EKH_STORAGE_ROOT": str(tmp_path / "pdfs"),
    }
    log_path = tmp_path / "server.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
            ],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                content = log_path.read_text()
                match = re.search(r"Uvicorn running on (http://127.0.0.1:\d+)", content)
                if match:
                    with httpx.Client(base_url=match[1], timeout=10) as client:
                        yield client
                    return
                if process.poll() is not None:
                    raise AssertionError(content)
                time.sleep(0.1)
            raise AssertionError("Uvicorn startup timeout")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_real_http_upload_and_process_restart(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf = buffer.getvalue()
    with server(tmp_path) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.post(
            "/api/v1/components",
            json={
                "manufacturer": "Synthetic Test",
                "part_number": "LIVE-001",
            },
        )
        assert response.status_code == 201
        component_id = response.json()["id"]
        for label in ("A", "B"):
            response = client.post(
                f"/api/v1/components/{component_id}/revisions",
                data={"revision": label, "document_title": "Datasheet"},
                files={"file": ("synthetic.pdf", pdf, "application/pdf")},
            )
            assert response.status_code == 201, response.text
        revision_id = response.json()["id"]
        assert client.get(f"/api/v1/revisions/{revision_id}/file").content == pdf
    with server(tmp_path) as client:
        result = client.get("/api/v1/components?q=LIVE-001").json()
        assert result["total"] == 1
        detail = client.get(f"/api/v1/components/{component_id}").json()
        assert len(detail["documents"][0]["revisions"]) == 2
        download = client.get(f"/api/v1/revisions/{revision_id}/file?download=true")
        assert download.content == pdf
        assert download.headers["content-disposition"].startswith("attachment")
