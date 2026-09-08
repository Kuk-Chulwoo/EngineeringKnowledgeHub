"""Bounded ephemeral native text; all page numbers are physical and one-based."""

import hashlib
import re
from dataclasses import dataclass

import pypdf
from pypdf import PdfReader

from ..engineering.repository import require
from .config import ExtractionSettings

PARSER_VERSION = "pypdf-" + pypdf.__version__ + "/native-selection-1"
KEYWORDS = {
    "identity": ("description", "features", "texas instruments", "part number"),
    "package": ("package", "mechanical", "dimension", "pitch", "exposed", "qfn"),
    "pins": ("pin configuration", "pin functions", "pin description", "terminal", "pin no"),
    "interfaces": (
        "spi",
        "uart",
        "i2c",
        "gpio",
        "serial",
        "analog",
        "rf",
        "clock",
        "reset",
        "supply",
    ),
}


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class DocumentText:
    revision_id: int
    sha256: str
    page_count: int
    pages: dict[int, str]
    truncated_pages: list[int]

    def select(self, pass_name: str, settings: ExtractionSettings) -> dict[int, str]:
        scores = {
            n: sum(t.lower().count(word) for word in KEYWORDS[pass_name])
            + (20 if pass_name == "identity" and n == 1 else 0)
            for n, t in self.pages.items()
            if t.strip()
        }
        ranked = sorted(scores, key=lambda n: (-scores[n], n))
        selected = {}
        remaining = settings.chars_per_pass
        for n in ranked[: settings.pages_per_pass]:
            if remaining <= 0:
                break
            selected[n] = self.pages[n][: min(remaining, settings.chars_per_page)]
            remaining -= len(selected[n])
        require(bool(selected), "No native text available; OCR is not implemented", 422)
        return dict(sorted(selected.items()))


def analyze(hub, revision_id: int, settings: ExtractionSettings) -> DocumentText:
    revision, stream = hub.open_revision(revision_id)
    with stream:
        h = hashlib.sha256()
        while chunk := stream.read(65536):
            h.update(chunk)
        require(h.hexdigest() == revision["sha256"], "Original PDF hash mismatch")
        stream.seek(0)
        reader = PdfReader(stream)
        count = len(reader.pages)
        require(0 < count <= settings.max_document_pages, "PDF exceeds configured page bound", 422)
        pages, truncated = {}, []
        for number, page in enumerate(reader.pages, 1):
            # Bound decoded content before native extraction. Reject oversized pages instead of guessing.
            content = page.get_contents()
            require(
                content is None or len(content.get_data()) <= 2_000_000,
                "PDF page content exceeds parser limit",
                422,
            )
            text = page.extract_text() or ""
            if len(text) > settings.chars_per_page:
                truncated.append(number)
            pages[number] = text[: settings.chars_per_page]
        require(any(t.strip() for t in pages.values()), "No native text; OCR required", 422)
        return DocumentText(revision_id, h.hexdigest(), count, pages, truncated)
