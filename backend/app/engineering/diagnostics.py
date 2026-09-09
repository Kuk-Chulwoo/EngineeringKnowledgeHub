"""Allowlisted worker diagnostics. Never serialize exceptions, inputs, context or traces."""

import json
import logging
import re
from dataclasses import dataclass

from pydantic import ValidationError

from ..ai.providers.base import ProviderFailure
from ..services import ServiceError

logger = logging.getLogger("ekh.worker")

# Exact application-owned messages only. Dynamic validator messages may contain source values.
SAFE_MESSAGES = frozenset(
    {
        "Provider object has missing or unknown schema properties",
        "Provider revision mismatch",
        "Wrong pass kind or package scope",
        "Unknown field key",
        "Evidence does not resolve to selected native page text",
        "Evidence belongs to another revision",
        "Evidence page outside original PDF",
        "Original PDF hash mismatch",
        "Run/source mismatch",
        "Run cancelled",
        "Run cannot publish",
        "Provider provenance mismatch",
        "Run cannot record pass",
        "External AI transmission is disabled",
        "External AI is disabled for this revision",
        "OpenAI model/key must be configured locally",
        "Worker model/prompt/parser changed; explicitly retry as new run",
        "PDF exceeds configured page bound",
        "PDF page content exceeds parser limit",
        "No native text; OCR required",
        "No native text available; OCR is not implemented",
        "Candidate source revision mismatch",
        "Duplicate entity keys",
        "Duplicate claims",
        "Exactly one component identity required",
        "Package coverage is missing",
        "Reference target missing or wrong kind",
        "Package scope mismatch",
        "Dimension minimum <= nominal <= maximum violated",
        "Interface membership crosses packages",
        "Duplicate interface membership",
        "Duplicate pin designators",
        "Exposed pad presence and pin table disagree",
        "Pin count mismatch: missing or extra pins",
    }
)
PROVIDER_MESSAGES = {
    "PROVIDER_TIMEOUT": "Provider request timed out",
    "PROVIDER_HTTP_FAILURE": "Provider HTTP request failed",
    "PROVIDER_MALFORMED": "Provider response could not be decoded",
    "PROVIDER_INCOMPLETE": "Provider response was incomplete",
    "PROVIDER_REFUSAL_OR_MALFORMED": "Provider refused or returned an unsupported response shape",
    "PROVIDER_RESPONSE_TOO_LARGE": "Provider response exceeded the size bound",
}
SAFE_LOCATIONS = frozenset(
    {
        "schema_version",
        "source_revision_id",
        "entities",
        "local_key",
        "kind",
        "scope_key",
        "fields",
        "key",
        "value",
        "availability",
        "confidence",
        "confidence_basis",
        "evidence",
        "transformation",
        "review_status",
        "page_number",
        "printed_page_label",
        "source_text",
        "source_text_sha256",
        "region",
        "locator_method",
        "locator_version",
        "evidence_role",
        "decimal",
        "unit",
        "provenance",
        "passes",
        "model_version",
        "request_sha256",
        "response_sha256",
    }
)
SAFE_TYPES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "literal_error",
        "value_error",
        "string_type",
        "int_type",
        "float_type",
        "bool_type",
        "list_type",
        "dict_type",
        "model_type",
        "none_required",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "finite_number",
        "string_too_short",
        "string_too_long",
        "string_pattern_mismatch",
        "too_short",
        "too_long",
    }
)


def sanitized_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        # Pydantic str(error), msg, input and ctx can all contain the entire PDF/provider payload.
        diagnostics = []
        for item in error.errors(include_input=False, include_context=False, include_url=False)[:8]:
            location = ".".join(
                str(part)
                if type(part) is int and 0 <= part <= 20000
                else part
                if type(part) is str and part in SAFE_LOCATIONS
                else "*"
                for part in item["loc"][:12]
            )
            kind = item["type"] if item["type"] in SAFE_TYPES else "validation_error"
            diagnostics.append(f"{location or 'root'}: {kind}")
        return f"Schema validation failed ({error.error_count()} errors): " + "; ".join(diagnostics)
    if isinstance(error, ProviderFailure):
        return PROVIDER_MESSAGES.get(error.code, "Provider request failed; detail withheld")
    # Do not call str/repr on arbitrary exceptions, including exceptions chained by providers.
    message = (
        error.detail
        if isinstance(error, ServiceError)
        else (error.args[0] if type(error) is ValueError and len(error.args) == 1 else None)
    )
    if type(message) is str and message in SAFE_MESSAGES:
        return message
    if isinstance(error, ServiceError):
        return "Source or publication validation failed; dynamic detail withheld"
    if isinstance(error, ValueError):
        return "Candidate validation failed; dynamic detail withheld"
    return "Worker operation failed; exception detail withheld"


def identifier(value, secret: str = "") -> str:
    if (
        type(value) is not str
        or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value)
        or (secret and secret in value)
        or "sk-" in value.lower()
        or "authorization" in value.lower()
        or "bearer" in value.lower()
    ):
        return "withheld"
    return value


@dataclass
class RunDiagnostics:
    # Per invocation, never shared between runs or persisted in the immutable database.
    current_pass: str | None = None
    stage: str = "policy"

    def progress(self, stage: str, current_pass: str | None = None):
        self.stage = stage
        self.current_pass = current_pass

    def failure(self, run: dict, error: Exception, secret: str = ""):
        try:
            model = json.loads(run["provenance_json"]).get("model_identifier")
        except (ValueError, TypeError, AttributeError, KeyError):
            model = None
        event = {
            "event": "extraction_run_failed",
            "run_id": run["id"],
            "provider": identifier(run.get("provider"), secret),
            "model": identifier(model, secret),
            "current_pass": self.current_pass,
            "stage": self.stage,
            "exception_class": identifier(type(error).__name__, secret),
            "sanitized_error_message": sanitized_message(error),
        }
        logger.error(json.dumps(event, ensure_ascii=True), exc_info=False, stack_info=False)
