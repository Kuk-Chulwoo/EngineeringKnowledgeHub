import io
from typing import Any

from openpyxl import Workbook

from .parser import (
    MAX_IMPORT_BYTES,
    ParseFailure,
    detect_format,
    parse_csv,
    parse_xlsx,
    safe_filename,
    validate_rows,
)


class PinImportService:
    def template(self, output_format: str) -> tuple[bytes, str, str]:
        if output_format == "csv":
            return ("\ufeffPin Number,Pin Name\r\n".encode(), "text/csv; charset=utf-8", "pin_template.csv")
        if output_format == "xlsx":
            workbook = Workbook(write_only=True)
            worksheet = workbook.create_sheet("Pins")
            worksheet.append(["Pin Number", "Pin Name"])
            output = io.BytesIO()
            workbook.save(output)
            return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pin_template.xlsx"
        raise ValueError("Unsupported template format")

    def preview(self, filename: str, content: bytes) -> dict[str, Any]:
        clean_name = safe_filename(filename)
        output_format: str | None = None
        try:
            output_format = detect_format(clean_name)
            if len(content) > MAX_IMPORT_BYTES:
                raise ParseFailure("FILE_TOO_LARGE", "Pin import file exceeds 2 MiB")
            rows = parse_csv(content) if output_format == "csv" else parse_xlsx(content)
            pins, errors = validate_rows(rows)
        except ParseFailure as error:
            pins = []
            errors = [{"code": error.code, "row": None, "field": None, "message": error.message}]
        return {"filename": clean_name, "format": output_format, "valid": not errors,
                "count": len(pins), "errors": errors, "warnings": [], "pins": pins}
