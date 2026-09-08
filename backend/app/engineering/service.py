import hashlib
from typing import Any, Protocol

from pypdf import PdfReader

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
    def __init__(self, repository: EngineeringRepository, hub: HubService):
        self.repository = repository
        self.hub = hub

    def verify_source(self, revision_id: int) -> tuple[str, int]:
        revision, stream = self.hub.open_revision(revision_id)
        with stream:
            digest = hashlib.sha256()
            while chunk := stream.read(65536):
                digest.update(chunk)
            source_hash = digest.hexdigest()
            require(source_hash == revision["sha256"], "Original PDF hash mismatch", 409)
            require(
                source_hash == hashlib.sha256(fixture_pdf()).hexdigest(),
                "Synthetic provider accepts only the fabricated SYNTH-DEMO-4 fixture PDF",
                422,
            )
            stream.seek(0)
            return source_hash, len(PdfReader(stream).pages)

    def create(self, revision_id: int, actor: str, retry_of: int | None = None) -> dict:
        source_hash, pages = self.verify_source(revision_id)
        run = self.repository.create_run(
            revision_id, source_hash, pages, PROVENANCE, actor, retry_of
        )
        return self.repository.read_run(run["id"])

    def work_once(self, provider: Provider | None = None) -> bool:
        run = self.repository.claim_next()
        if run is None:
            return False
        try:
            source_hash, pages = self.verify_source(run["source_revision_id"])
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
            self.repository.fail(run["id"], run["lease_token"], code)
        return True
