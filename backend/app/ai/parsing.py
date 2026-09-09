"""Bounded ephemeral native text; all page numbers are physical and one-based."""

import hashlib
import re
import unicodedata
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


# Only encoding/presentation equivalents. Do not remove punctuation, join words,
# dehyphenate line endings, case-fold, reorder tokens, or normalize units/numbers.
PDF_CHARACTER_EQUIVALENTS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00d7": "x",
    }
)


def canonical_native_text(text: str) -> str:
    """Conservative PDF character normalization for comparison only.

    Restrict NFKC to fullwidth ASCII and Latin ff/fi/fl/ffi/ffl ligatures.
    Blanket NFKC would also flatten exponents, circled numbers and unit symbols,
    which can change engineering meaning (for example m² versus m2).
    Unicode spaces are already handled by normalized(); source strings stay intact.
    """
    text = "".join(
        unicodedata.normalize("NFKC", char)
        if "\uff01" <= char <= "\uff5e" or "\ufb00" <= char <= "\ufb04"
        else char
        for char in text
    )
    return normalized(text.translate(PDF_CHARACTER_EQUIVALENTS))


def resolves_native_evidence(quote: str, selected_page_text: str) -> bool:
    """Exact whitespace-normalized substring first, canonical substring only on failure."""
    exact_quote = normalized(quote)
    if not exact_quote:
        return False
    if exact_quote in normalized(selected_page_text):
        return True
    canonical_quote = canonical_native_text(quote)
    return bool(canonical_quote) and canonical_quote in canonical_native_text(selected_page_text)


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
