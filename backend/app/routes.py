from collections.abc import Iterator
from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from .schemas import Component, ComponentCreate, ComponentDetail, ComponentList, Revision
from .services import HubService

router = APIRouter(prefix="/api/v1")


def service(request: Request) -> HubService:
    return request.app.state.service


Service = Annotated[HubService, Depends(service)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@router.post("/components", response_model=Component, status_code=201)
def create_component(payload: ComponentCreate, hub: Service) -> dict:
    return hub.create_component(payload)


@router.get("/components", response_model=ComponentList)
def search_components(
    hub: Service,
    q: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    return hub.repository.search(q.strip(), limit, offset)


@router.get("/components/{component_id}", response_model=ComponentDetail)
def get_component(component_id: int, hub: Service) -> dict:
    return hub.component(component_id)


@router.post("/components/{component_id}/revisions", response_model=Revision, status_code=201)
def upload_revision(
    component_id: int,
    hub: Service,
    file: Annotated[UploadFile, File()],
    revision: Annotated[str, Form(min_length=1, max_length=200)],
    document_title: Annotated[str, Form(min_length=1, max_length=200)] = "Datasheet",
    datasheet_date: Annotated[date | None, Form()] = None,
) -> dict:
    try:
        return hub.upload(
            component_id, document_title, revision, datasheet_date, file.filename or "", file.file
        )
    finally:
        file.file.close()


@router.get("/revisions/{revision_id}/file")
def revision_file(revision_id: int, hub: Service, download: bool = False) -> StreamingResponse:
    revision, stream = hub.open_revision(revision_id)

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := stream.read(64 * 1024):
                yield chunk
        finally:
            stream.close()

    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(revision['filename'], safe='')}",
            "Content-Length": str(revision["size_bytes"]),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
