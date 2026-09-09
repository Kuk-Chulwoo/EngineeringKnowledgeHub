import pytest
from test_engineering_schema import field, raw

from backend.app.ai.prompts import prompt
from backend.app.engineering.schema import ENUMS, CandidateSet, validate_candidates


def test_package_prompt_lists_every_canonical_pin_count_basis():
    text = prompt("package")
    for value in ENUMS["pin_count_basis"]:
        assert value in text
    assert "family, type and manufacturer_package_code remain verbatim source text" in text


def test_invalid_pin_count_basis_remains_rejected():
    data = raw()
    field(data, "pkg", "pin_count_basis")["value"] = "LEADS_AND_PAD"
    with pytest.raises(ValueError):
        validate_candidates(CandidateSet.model_validate(data), 1, 3)
