"""In-memory structural context; preserve exception type/message and public failure mapping."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationDetail:
    loc: tuple
    type: str


def validation_error(message: str, loc: tuple, validation_type: str) -> ValueError:
    error = ValueError(message)
    error.validation_detail = ValidationDetail(loc, validation_type)
    return error


def prefix_validation(error: ValueError, prefix: tuple):
    detail = getattr(error, "validation_detail", None)
    if isinstance(detail, ValidationDetail):
        error.validation_detail = ValidationDetail(prefix + detail.loc, detail.type)
    else:
        # Pydantic errors retain their original loc/type; only prepend caller structure.
        error.validation_prefix = prefix + getattr(error, "validation_prefix", ())
    return error
