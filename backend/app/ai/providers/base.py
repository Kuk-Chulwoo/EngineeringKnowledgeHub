from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProviderResult:
    payload: dict
    request_sha256: str
    response_sha256: str
    model_version: str | None


class CandidateProvider(Protocol):
    def generate(
        self, model: str, prompt: str, content: dict, schema: dict, max_output_tokens: int
    ) -> ProviderResult: ...
