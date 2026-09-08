import hashlib
from typing import Any, Protocol

from pypdf import PdfReader

from ..ai.config import ProviderPolicy
from ..ai.extraction import extract, provenance
from ..ai.parsing import analyze
from ..ai.providers.openai_provider import OpenAIProvider, ProviderFailure
from ..services import HubService, ServiceError
from .repository import EngineeringRepository, require
from .schema import CandidateSet
from .synthetic import PROVENANCE, candidates, fixture_pdf


class Provider(Protocol):
    def extract(self, revision_id: int) -> dict[str, Any]: ...


class SyntheticProvider:
    def extract(self, revision_id: int) -> dict[str, Any]:
        return candidates(revision_id).model_dump()


class EngineeringService:
    def __init__(
        self,
        repository: EngineeringRepository,
        hub: HubService,
        policy: ProviderPolicy | None = None,
    ):
        self.repository = repository
        self.hub = hub
        self.policy = policy or ProviderPolicy()
        self.providers = {"openai": lambda: OpenAIProvider(self.policy.api_key)}

    def verify_source(self, revision_id: int, synthetic: bool = False) -> tuple[str, int]:
        revision, stream = self.hub.open_revision(revision_id)
        with stream:
            digest = hashlib.sha256()
            while chunk := stream.read(65536):
                digest.update(chunk)
            source_hash = digest.hexdigest()
            require(source_hash == revision["sha256"], "Original PDF hash mismatch", 409)
            require(
                not synthetic or source_hash == hashlib.sha256(fixture_pdf()).hexdigest(),
                "Synthetic provider accepts only the fabricated SYNTH-DEMO-4 fixture PDF",
                422,
            )
            stream.seek(0)
            return source_hash, len(PdfReader(stream).pages)

    def create(self, revision_id: int, actor: str, retry_of: int | None = None) -> dict:
        source_hash, pages = self.verify_source(revision_id, synthetic=True)
        run = self.repository.create_run(
            revision_id, source_hash, pages, PROVENANCE, actor, retry_of
        )
        return self.repository.read_run(run["id"])

    def create_real(self, revision_id, actor, settings, retry_of=None):
        self.policy.authorize(revision_id)
        document = analyze(self.hub, revision_id, settings)
        run = self.repository.create_run(
            revision_id,
            document.sha256,
            document.page_count,
            provenance(self.policy.model, settings),
            actor,
            retry_of,
        )
        return self.repository.read_run(run["id"])

    def work_once(self, provider: Provider | None = None) -> bool:
        run = self.repository.claim_next(lease_seconds=600)
        if run is None:
            return False
        try:
            if run["provider"] != "synthetic":
                self.policy.authorize(run["source_revision_id"])
                data = extract(self, run, self.providers[run["provider"]]())
                self.repository.publish(run["id"], run["lease_token"], data)
                return True
            source_hash, pages = self.verify_source(run["source_revision_id"], synthetic=True)
            require(
                source_hash == run["source_sha256"] and pages == run["page_count"],
                "Run/source mismatch",
            )
            data = CandidateSet.model_validate(
                (provider or SyntheticProvider()).extract(run["source_revision_id"])
            )
            self.repository.publish(run["id"], run["lease_token"], data)
        except Exception as error:  # noqa: BLE001 - durable worker boundary, redact provider failures
            code = "INVALID_OUTPUT" if isinstance(error, ValueError) else "SOURCE_OR_WORKER_ERROR"
            if isinstance(error, ServiceError):
                code = "PUBLICATION_OR_SOURCE_REJECTED"
            if isinstance(error, ProviderFailure):
                code = error.code
            self.repository.fail(run["id"], run["lease_token"], code)
        return True
