from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse

from .schemas import (
    PinValidationUpdate,
    SchematicSymbol,
    SymbolCreate,
    SymbolLifecycleUpdate,
    SymbolUpdate,
)
from .service import SymbolService

router = APIRouter(prefix="/api/v1")


def service(request: Request) -> SymbolService:
    return request.app.state.symbols


Service = Annotated[SymbolService, Depends(service)]


@router.get("/components/{component_id}/symbols", response_model=list[SchematicSymbol])
def list_symbols(component_id: int, symbols: Service) -> list[dict]:
    return symbols.list_for_component(component_id)


@router.post(
    "/components/{component_id}/symbols", response_model=SchematicSymbol, status_code=201
)
def create_symbol(
    component_id: int, payload: SymbolCreate, symbols: Service
) -> dict:
    return symbols.create(component_id, payload)


@router.get("/symbols/{symbol_id}", response_model=SchematicSymbol)
def get_symbol(symbol_id: int, symbols: Service) -> dict:
    return symbols.get(symbol_id)


@router.patch("/symbols/{symbol_id}", response_model=SchematicSymbol)
def update_symbol(symbol_id: int, payload: SymbolUpdate, symbols: Service) -> dict:
    return symbols.update(symbol_id, payload)


@router.post("/symbols/{symbol_id}/file", response_model=SchematicSymbol)
def upload_symbol_file(
    symbol_id: int, symbols: Service, file: Annotated[UploadFile, File()]
) -> dict:
    try:
        return symbols.upload_file(symbol_id, file.filename or "", file.file)
    finally:
        file.file.close()


@router.get("/symbols/{symbol_id}/file")
def symbol_file(
    symbol_id: int, symbols: Service, download: bool = False
) -> StreamingResponse:
    symbol, stream = symbols.open_file(symbol_id)

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := stream.read(64 * 1024):
                yield chunk
        finally:
            stream.close()

    disposition = "attachment" if download else "inline"
    filename = quote(symbol["source_filename"], safe="")
    return StreamingResponse(
        chunks(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}",
            "Content-Length": str(symbol["size_bytes"]),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/symbols/{symbol_id}/pin-validation", response_model=SchematicSymbol)
def update_pin_validation(
    symbol_id: int, payload: PinValidationUpdate, symbols: Service
) -> dict:
    return symbols.update_pin_validation(symbol_id, payload)


@router.post("/symbols/{symbol_id}/lifecycle", response_model=SchematicSymbol)
def update_symbol_lifecycle(
    symbol_id: int, payload: SymbolLifecycleUpdate, symbols: Service
) -> dict:
    return symbols.update_lifecycle(symbol_id, payload)
