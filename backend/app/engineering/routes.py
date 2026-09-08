from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..ai.config import ExtractionSettings
from ..ai.golden import GoldenManifest, GoldenService
from .repository import require
from .schema import Claim
from .service import EngineeringService
from .synthetic import fixture_pdf

router = APIRouter(prefix="/api/v1")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class RunInput(Input):
    provider: Literal["synthetic", "openai"] = "synthetic"
    external_transmission_authorized: bool = False
    settings: ExtractionSettings | None = None
    retry_of_run_id: int | None = Field(default=None, gt=0)


class ReviewInput(Input):
    expected_sequence: int = Field(gt=0)
    status: Literal["ENGINEER_APPROVED", "ENGINEER_REJECTED"]
    reason: str = Field(min_length=1, max_length=1000)


class CorrectionInput(Input):
    expected_sequence: int = Field(gt=0)
    claim: Claim


class SnapshotInput(Input):
    run_id: int = Field(gt=0)
    selected_package_entity_id: int = Field(gt=0)
    field_ids: list[int] = Field(min_length=1, max_length=20000)
    purpose: Literal["engineering-review"] = "engineering-review"


def engineer(request: Request) -> str:
    return request.app.state.reviewer.authenticate(request).actor


def service(request: Request) -> EngineeringService:
    return request.app.state.engineering


Actor = Annotated[str, Depends(engineer)]
Engineering = Annotated[EngineeringService, Depends(service)]


@router.post("/reviewer/session")
def login(payload: Login, request: Request, response: Response) -> dict:
    token, session = request.app.state.reviewer.login(request, payload.name, payload.password)
    response.set_cookie(
        "ekh_reviewer",
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/api/v1",
        max_age=8 * 3600,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"actor": session.actor, "csrf_token": session.csrf}


@router.get("/reviewer/session")
def session(request: Request, response: Response) -> dict:
    current = request.app.state.reviewer.authenticate(request, mutation=False)
    response.headers["Cache-Control"] = "no-store"
    return {"actor": current.actor, "csrf_token": current.csrf}


@router.delete("/reviewer/session", status_code=204)
def logout(request: Request, response: Response) -> None:
    request.app.state.reviewer.logout(request)
    response.delete_cookie("ekh_reviewer", path="/api/v1")


@router.get("/engineering/synthetic-fixture/file")
def synthetic_file() -> Response:
    return Response(
        fixture_pdf(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="FABRICATED-SYNTH-DEMO-4.pdf"'},
    )


@router.post("/revisions/{revision_id}/extraction-runs", status_code=201)
def create_run(revision_id: int, payload: RunInput, actor: Actor, hub: Engineering) -> dict:
    if payload.provider == "synthetic":
        require(
            payload.settings is None and not payload.external_transmission_authorized,
            "Synthetic runs do not accept external settings",
            422,
        )
        return hub.create(revision_id, actor, payload.retry_of_run_id)
    require(
        payload.external_transmission_authorized and payload.settings is not None,
        "Explicit external transmission authorization and package scope required",
        422,
    )
    return hub.create_real(revision_id, actor, payload.settings, payload.retry_of_run_id)


@router.get("/revisions/{revision_id}/extraction-runs")
def list_runs(revision_id: int, hub: Engineering) -> list[dict]:
    # Check existence without revealing internal metadata.
    revision = hub.hub.repository.revision(revision_id)
    if revision is None:
        from ..services import ServiceError

        raise ServiceError(404, "Revision not found")
    return hub.repository.list_runs(revision_id)


@router.get("/extraction-runs/{run_id}")
def read_run(run_id: int, hub: Engineering) -> dict:
    return hub.repository.read_run(run_id)


@router.post("/extraction-runs/{run_id}/cancel")
def cancel_run(run_id: int, actor: Actor, hub: Engineering) -> dict:
    return hub.repository.cancel(run_id)


@router.post("/engineering-fields/{field_id}/reviews", status_code=201)
def review(field_id: int, payload: ReviewInput, actor: Actor, hub: Engineering) -> dict:
    return hub.repository.review(
        field_id,
        payload.expected_sequence,
        payload.status,
        actor,
        payload.reason.strip() or "Engineer decision",
    )


@router.post("/engineering-fields/{field_id}/corrections", status_code=201)
def correct(field_id: int, payload: CorrectionInput, actor: Actor, hub: Engineering) -> dict:
    field = hub.repository.correct(field_id, payload.expected_sequence, payload.claim, actor)
    return {"field_id": field, "review_status": "ENGINEER_DRAFT"}


@router.post("/approved-snapshots", status_code=201)
def snapshot(payload: SnapshotInput, actor: Actor, hub: Engineering) -> dict:
    run = hub.repository.read_run(payload.run_id)
    hub.verify_source(run["source_revision_id"])
    return hub.repository.snapshot(
        payload.run_id, payload.selected_package_entity_id, payload.field_ids, actor
    )


@router.get("/approved-snapshots/{snapshot_id}")
def read_snapshot(snapshot_id: int, hub: Engineering) -> dict:
    return hub.repository.read_snapshot(snapshot_id)


@router.get("/engineering/provider-config")
def provider_config(hub: Engineering) -> dict:
    return hub.policy.public()


class GoldenInput(Input):
    manifest: GoldenManifest
    manually_curated_from_source: Literal[True]


class GoldenApproval(Input):
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_against_original_pdf: Literal[True]


@router.get("/engineering/golden-schema")
def golden_schema() -> dict:
    return GoldenManifest.model_json_schema()


@router.post("/golden-references", status_code=201)
def create_golden(payload: GoldenInput, actor: Actor, hub: Engineering) -> dict:
    return GoldenService(hub).create(payload.manifest, actor)


@router.get("/revisions/{revision_id}/golden-references")
def list_golden(revision_id: int, hub: Engineering) -> list[dict]:
    return GoldenService(hub).list(revision_id)


@router.get("/golden-references/{golden_id}")
def read_golden(golden_id: int, hub: Engineering) -> dict:
    return GoldenService(hub).read(golden_id)


@router.post("/golden-references/{golden_id}/approval")
def approve_golden(golden_id: int, payload: GoldenApproval, actor: Actor, hub: Engineering) -> dict:
    return GoldenService(hub).approve(golden_id, payload.expected_sha256, actor)


@router.get("/golden-references/{golden_id}/evaluations/{run_id}")
def evaluate_golden(golden_id: int, run_id: int, hub: Engineering) -> dict:
    return GoldenService(hub).evaluate(golden_id, run_id)
