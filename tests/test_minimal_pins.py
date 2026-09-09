import pytest

from backend.app.ai.prompts import prompt
from backend.app.ai.wire import parse_output, wire_schema
from backend.app.engineering.schema import values


def payload(records):
    return {
        "schema_version": "engineering-extraction/0.1",
        "source_revision_id": 1,
        "pins": records,
    }


def record(number, name, page=4):
    return {
        "availability": "PRESENT",
        "pin_number": number,
        "pin_name": name,
        "source_page": page,
    }


def parse(records, text="1 GND 25 RESET A1 SDA B12 SCL EP PAD"):
    return parse_output(payload(records), "pins", 1, 10, {4: text}, "PKG", "pkg", "0")


def test_numeric_and_alphanumeric_pin_identifiers_remain_strings():
    entities = parse([record("1", "GND"), record("25", "RESET"), record("A1", "SDA")])
    assert [values(entity)["number"] for entity in entities] == ["1", "25", "A1"]
    assert [values(entity)["source_name"] for entity in entities] == ["GND", "RESET", "SDA"]


@pytest.mark.parametrize("identifier", ["EP", "PAD"])
def test_exposed_pad_identifiers_are_allowed_and_classified(identifier):
    entity = parse([record(identifier, identifier)])[0]
    assert values(entity)["number"] == identifier
    assert values(entity)["is_exposed_pad"] is True


@pytest.mark.parametrize(
    "number,name",
    [("", "GND"), ("   ", "GND"), ("1", ""), ("1", "   ")],
)
def test_blank_pin_number_or_name_is_rejected(number, name):
    with pytest.raises(ValueError):
        parse([record(number, name)])


def test_pin_number_must_be_a_string():
    with pytest.raises(ValueError):
        parse([record(1, "GND")])


def test_pin_name_must_match_native_source_without_renaming():
    with pytest.raises(ValueError, match="Evidence does not resolve"):
        parse([record("1", "ground")], text="1 GND")


def test_ambiguous_pin_does_not_gain_invented_values():
    ambiguous = {
        "availability": "AMBIGUOUS",
        "pin_number": None,
        "pin_name": None,
        "source_page": 4,
    }
    entity = parse([ambiguous])[0]
    assert "number" not in values(entity) and "source_name" not in values(entity)


def test_minimal_pin_wire_contract_excludes_interpreted_metadata_and_quotes():
    contract_text = str(wire_schema("pins")) + prompt("pins")
    assert "pin_number" in contract_text and "pin_name" in contract_text
    for excluded in (
        "primary_function",
        "electrical_type",
        "functional_group",
        "normalized_name",
        "source_text",
    ):
        assert excluded not in contract_text
