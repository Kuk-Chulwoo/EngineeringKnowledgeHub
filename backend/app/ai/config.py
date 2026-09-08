"""Server-owned policy; credentials never enter run metadata."""

import os
from dataclasses import dataclass, field

from pydantic import Field

from ..engineering.repository import require
from ..engineering.schema import StrictModel


class ExtractionSettings(StrictModel):
    package_scope: str = Field(min_length=1, max_length=100)
    max_document_pages: int = Field(default=200, ge=1, le=300)
    pages_per_pass: int = Field(default=6, ge=1, le=10)
    chars_per_page: int = Field(default=12000, ge=1000, le=20000)
    chars_per_pass: int = Field(default=40000, ge=1000, le=60000)
    max_output_tokens: int = Field(default=16000, ge=1000, le=32000)


@dataclass(frozen=True)
class ProviderPolicy:
    enabled: bool = False
    model: str = ""
    api_key: str = field(default="", repr=False)
    denied_revisions: frozenset[int] = frozenset()

    @classmethod
    def from_env(cls):
        return cls(
            os.getenv("EKH_EXTERNAL_AI_ENABLED", "false").lower() == "true",
            os.getenv("EKH_OPENAI_MODEL", "").strip(),
            os.getenv("OPENAI_API_KEY", ""),
            frozenset(
                int(v) for v in os.getenv("EKH_AI_DENIED_REVISIONS", "").split(",") if v.strip()
            ),
        )

    def authorize(self, revision_id: int):
        require(self.enabled, "External AI transmission is disabled", 403)
        require(
            revision_id not in self.denied_revisions,
            "External AI is disabled for this revision",
            403,
        )
        require(
            bool(self.model and self.api_key), "OpenAI model/key must be configured locally", 503
        )

    def public(self):
        return {
            "provider": "openai",
            "model": self.model,
            "enabled": self.enabled,
            "configured": bool(self.model and self.api_key),
            "pipeline_version": "native-focused/1",
        }
