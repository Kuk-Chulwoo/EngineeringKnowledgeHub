"""Fabricated fixture only. No CC1120 data, external provider, or PDF interpretation."""

import io
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from .schema import CandidateSet, canonical

PROVENANCE = {
    "pipeline_version": "synthetic/1",
    "parser_version": "fixture/1",
    "provider": "synthetic",
    "model_identifier": "none-synthetic",
    "model_version": "fixture/1",
    "prompt_version": "not-applicable",
    "synthetic": True,
}


def candidates(revision_id: int) -> CandidateSet:
    entities: list[dict[str, Any]] = []
    line = 0

    def add(key: str, kind: str, fields: dict[str, Any]) -> None:
        nonlocal line
        claims = []
        for name, value in fields.items():
            snippet = f"{key}.{name} = {canonical(value)}"
            claims.append(
                {
                    "key": name,
                    "value": value,
                    "evidence": [
                        {
                            "source_revision_id": revision_id,
                            "page_number": line // 45 + 1,
                            "source_text": snippet,
                            "locator_method": "TEXT",
                            "locator_version": "fixture/1",
                        }
                    ],
                }
            )
            line += 1
        entities.append(
            {"local_key": key, "kind": kind, "scope_key": "FAB-PKG-A", "fields": claims}
        )

    add(
        "identity",
        "COMPONENT_IDENTITY",
        {
            "manufacturer": "Fabricated Example Instruments",
            "part_number": "SYNTH-DEMO-4",
            "description": "FABRICATED TEST COMPONENT. Not a real device.",
        },
    )
    add(
        "pkg",
        "PACKAGE",
        {
            "family": "TEST-QFN",
            "type": "Fabricated demonstration package",
            "manufacturer_package_code": "FAB4X",
            "variant_selector": "SYNTH-DEMO-4/FAB4X",
            "lead_count": 4,
            "pin_count_basis": "LEADS_ONLY",
            "exposed_pad_present": True,
            "body_width.minimum": {"decimal": "2.90", "unit": "mm"},
            "body_width.nominal": {"decimal": "3.00", "unit": "mm"},
            "body_width.maximum": {"decimal": "3.10", "unit": "mm"},
            "body_length.nominal": {"decimal": "3.00", "unit": "mm"},
            "body_height.nominal": {"decimal": "0.80", "unit": "mm"},
            "pitch.nominal": {"decimal": "0.65", "unit": "mm"},
        },
    )
    for key, number, name, normalized, function, electrical in [
        ("p1", "1", "CLK/SCK", "SCK", "Serial clock", "INPUT"),
        ("p2", "2", "DIO/GPIO0", "DIO", "Serial data", "BIDIRECTIONAL"),
        ("p3", "3", "VDD", "VDD", "Supply", "POWER_IN"),
        ("p4", "4", "GND", "GND", "Ground", "GROUND"),
        ("ep", "EP", "THERMAL_GND", "THERMAL_GND", "Exposed ground pad", "GROUND"),
    ]:
        fields: dict[str, Any] = {
            "number": number,
            "source_name": name,
            "normalized_name": normalized,
            "primary_function": function,
            "electrical_type": electrical,
            "functional_group": "supply" if key in ("p3", "p4", "ep") else "digital",
            "package_ref": "pkg",
            "is_exposed_pad": key == "ep",
        }
        if key == "p2":
            fields["alternate_function.gpio"] = "General purpose input/output in GPIO mode"
        add(key, "PIN", fields)
    for key, kind in [
        ("spi", "SPI"),
        ("gpio", "GPIO"),
        ("power", "POWER"),
        ("clock", "CLOCK_RESET"),
    ]:
        add(key, "INTERFACE", {"kind": kind, "name": f"Fabricated {kind}", "package_ref": "pkg"})
    for index, (interface, pin, role, mode) in enumerate(
        [
            ("spi", "p1", "clock", "serial"),
            ("spi", "p2", "data", "serial"),
            ("gpio", "p2", "gpio", "gpio"),
            ("power", "p3", "supply", "always"),
            ("power", "p4", "ground", "always"),
            ("power", "ep", "ground", "always"),
            ("clock", "p1", "clock", "serial"),
        ]
    ):
        add(
            f"link{index}",
            "INTERFACE_PIN",
            {
                "interface_ref": interface,
                "pin_ref": pin,
                "role": role,
                "mode": mode,
            },
        )
    return CandidateSet.model_validate(
        {
            "source_revision_id": revision_id,
            "provenance": PROVENANCE,
            "entities": entities,
        }
    )


def fixture_pdf() -> bytes:
    lines = [
        field.evidence[0].source_text
        for entity in candidates(1).entities
        for field in entity.fields
    ]
    writer = PdfWriter()
    writer.add_metadata({"/Title": "FABRICATED SYNTH-DEMO-4 fixture, not an engineering datasheet"})
    for start in range(0, len(lines), 45):
        page = writer.add_blank_page(width=850, height=700)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Courier"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                ),
            }
        )
        commands = ["BT /F1 8 Tf 35 665 Td 13 TL"]
        for line in lines[start : start + 45]:
            escaped = (line or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({escaped}) Tj T*")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
