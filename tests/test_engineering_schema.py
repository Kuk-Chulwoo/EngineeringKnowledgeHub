import copy
import io

import pytest
from pypdf import PdfReader

from backend.app.engineering.schema import CandidateSet, validate_candidates
from backend.app.engineering.synthetic import candidates, fixture_pdf


def raw():
    return candidates(1).model_dump()


def field(data, entity, key):
    return next(
        f
        for e in data["entities"]
        if e["local_key"] == entity
        for f in e["fields"]
        if f["key"] == key
    )


def test_synthetic_fixture_is_deterministic_and_evidenced():
    pdf = fixture_pdf()
    assert pdf == fixture_pdf()
    reader = PdfReader(io.BytesIO(pdf))
    data = candidates(1)
    assert validate_candidates(data, 1, len(reader.pages)) == []
    for entity in data.entities:
        for claim in entity.fields:
            evidence = claim.evidence[0]
            assert evidence.source_text in reader.pages[evidence.page_number - 1].extract_text()


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["entities"][0].update(kind="UNKNOWN"),
        lambda d: d["entities"][0]["fields"][0].update(key="unsupported"),
        lambda d: field(d, "pkg", "lead_count").update(value=True),
        lambda d: field(d, "pkg", "lead_count").update(value=5),
        lambda d: field(d, "pkg", "exposed_pad_present").update(value=False),
        lambda d: field(d, "pkg", "pitch.nominal")["value"].update(unit="inch"),
        lambda d: field(d, "pkg", "pitch.nominal")["value"].update(decimal="NaN"),
        lambda d: field(d, "pkg", "body_width.minimum")["value"].update(decimal="4.00"),
        lambda d: field(d, "p2", "number").update(value="1"),
        lambda d: field(d, "p2", "package_ref").update(value="spi"),
        lambda d: field(d, "link0", "pin_ref").update(value="invented_pin"),
        lambda d: d["entities"][2].update(scope_key="wrong-package"),
        lambda d: d["entities"][0]["fields"].append(copy.deepcopy(d["entities"][0]["fields"][0])),
        lambda d: field(d, "p1", "source_name").update(review_status="ENGINEER_APPROVED"),
        lambda d: field(d, "p1", "source_name")["evidence"][0].update(source_revision_id=999),
        lambda d: field(d, "p1", "source_name")["evidence"][0].update(page_number=999),
        lambda d: field(d, "p1", "source_name")["evidence"][0].update(
            region={"x0": 0.9, "x1": 0.1, "y0": 0.0, "y1": 1.0}
        ),
        lambda d: field(d, "p1", "source_name")["evidence"][0].update(
            region={"x0": -0.1, "x1": 0.5, "y0": 0.0, "y1": 1.0}
        ),
        lambda d: d["entities"].pop(3),
    ],
)
def test_invalid_candidates_rejected(change):
    data = raw()
    change(data)
    with pytest.raises(ValueError):
        validate_candidates(CandidateSet.model_validate(data), 1, 3)


def test_count_including_exposed_pad_and_name_preservation():
    data = raw()
    field(data, "pkg", "lead_count")["value"] = 5
    field(data, "pkg", "pin_count_basis")["value"] = "INCLUDING_EXPOSED_PAD"
    assert validate_candidates(CandidateSet.model_validate(data), 1, 3) == []
    assert field(data, "p2", "source_name")["value"] == "DIO/GPIO0"
    assert field(data, "p2", "normalized_name")["value"] == "DIO"
