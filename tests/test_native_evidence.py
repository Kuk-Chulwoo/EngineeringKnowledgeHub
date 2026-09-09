"""Encoding-only evidence equivalence; all examples are invented test strings."""

import copy
import hashlib

import pytest
import test_real_extraction as real

from backend.app.ai import extraction, parsing, prompts
from backend.app.ai.wire import parse_output

client = real.client
settings = real.settings
no_external_network = real.no_external_network
ERROR = "Evidence does not resolve to selected native page text"


def resolve(quote, selected, page=2):
    payload = real.pass_payload(1, "package")
    for entity in payload["entities"]:
        for field in entity["fields"]:
            for evidence in field["evidence"]:
                evidence["source_text"] = quote
                evidence["source_text_sha256"] = None
                evidence["page_number"] = page
    original = copy.deepcopy(payload)
    result = parse_output(payload, "package", 1, 3, selected, real.SCOPE)
    assert payload == original
    for entity in result:
        for field in entity.fields:
            for evidence in field.evidence:
                assert evidence.source_text == quote
                assert evidence.source_text_sha256 == hashlib.sha256(quote.encode()).hexdigest()
    return result


@pytest.mark.parametrize(
    "quote,page",
    [
        ("Body size 5 mm.", "Package: Body size 5 mm. End."),
        ("Body size 5 mm.", "Package: Body\n size  5\tmm. End."),
        ("Body size 5 mm.", "Body\u00a0size\u202f5\u2009mm."),
        ("Range 1-5 mm.", "Range 1\u20135 mm."),
        ("The \"body\" is 'square'.", "The “body” is ‘square’."),
        ("Body 5 x 5 mm.", "Body 5 \u00d7 5 mm."),
        ("fine flat profile", "\ufb01ne \ufb02at pro\ufb01le"),
        ("Body 5 mm.", "\uff22\uff4f\uff44\uff59 \uff15 mm."),
    ],
)
def test_encoding_equivalents_pass_without_rewriting_source(quote, page):
    resolve(quote, {2: page})
    # Equivalence is symmetric; preserve the model's original typography too.
    if parsing.canonical_native_text(page) == parsing.canonical_native_text(quote):
        resolve(page, {2: quote})


@pytest.mark.parametrize(
    "dash", ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"]
)
def test_common_dash_variants_pass(dash):
    resolve("Pin 1-4", {2: "Pin 1" + dash + "4"})


@pytest.mark.parametrize(
    "quote,page",
    [
        ("The package width is 5 mm.", "The body measures 5 mm across."),
        ("Width 5 Length 6", "Length 6 Width 5"),
        ("Body 6 mm.", "Body 5 mm."),
        ("Body 5 cm.", "Body 5 mm."),
        ("Body 0.5 cm.", "Body 5 mm."),
        ("Body 5.0 mm.", "Body 5.00 mm."),
        ("Body 5 mm", "Body: 5 mm"),
        ("body 5 mm.", "Body 5 mm."),
        ("Body 5 mm.", "Body additional 5 mm."),
        ("surface", "sur-\nface"),
        ("Area m2.", "Area m\u00b2."),
        ("Pin 1.", "Pin \u2460."),
    ],
)
def test_paraphrase_order_numbers_units_and_other_meaning_changes_fail(quote, page):
    with pytest.raises(ValueError, match="^" + ERROR + "$"):
        resolve(quote, {2: page})


def test_wrong_physical_page_and_unselected_page_fail():
    for selected in ({1: "Body 5 x 5 mm.", 2: "Unrelated page"}, {1: "Body 5 x 5 mm."}):
        with pytest.raises(ValueError, match="^" + ERROR + "$"):
            resolve("Body 5 × 5 mm.", selected, page=2)


def test_no_cross_page_joining():
    with pytest.raises(ValueError, match="^" + ERROR + "$"):
        resolve("Body 5 x 5 mm.", {1: "Body 5 x", 2: "5 mm."})


def test_exact_normalized_match_precedes_canonical_fallback(monkeypatch):
    def forbidden(text):
        raise AssertionError("Fallback must not run after an exact normalized match")

    monkeypatch.setattr(parsing, "canonical_native_text", forbidden)
    resolve("Body size 5 mm.", {2: "Body\n size\u00a0 5 mm."})


def test_canonical_normalization_is_contiguous_and_does_not_remove_punctuation():
    assert (
        parsing.canonical_native_text("\u201c\ufb01ne\u201d\u00a05\u00d76\u2013mm.")
        == '"fine" 5x6-mm.'
    )
    assert not parsing.resolves_native_evidence("fine 5x6 mm.", '"fine" 5×6–mm.')
    assert not parsing.resolves_native_evidence("   ", "Some page")
    assert parsing.resolves_native_evidence("5 × 6", "Dimensions: 5 x 6 mm")


def test_prompt_version_and_hash_require_explicit_new_run(client, monkeypatch):
    service, calls = real.configure(client)
    revision = real.source(client)
    new_hash = prompts.prompt_hash()
    assert prompts.PROMPT_VERSION == "focused-native/2"
    added = (
        "Copy a contiguous quote exactly as it appears in supplied native page text;\n"
        "do not reconstruct table rows or paraphrase. Preserve numbers, units and punctuation.\n"
    )
    assert added in prompts.BASE and "verbatim supporting text" in prompts.BASE
    with monkeypatch.context() as patch:
        patch.setattr(prompts, "BASE", prompts.BASE.replace(added, ""))
        patch.setattr(extraction, "PROMPT_VERSION", "focused-native/1")
        old = real.start(client, revision)
        assert old["provenance"]["prompt_sha256"] != new_hash
    service.work_once()
    failed = service.repository.read_run(old["id"])
    assert failed["status"] == "FAILED" and failed["error_code"] == "PUBLICATION_OR_SOURCE_REJECTED"
    assert failed["provenance"] == old["provenance"] and not calls
    retry = real.start(client, revision, old["id"])
    assert retry["provenance"]["prompt_version"] == "focused-native/2"
    assert retry["provenance"]["prompt_sha256"] == new_hash
    service.work_once()
    assert service.repository.read_run(retry["id"])["status"] == "SUCCEEDED"
