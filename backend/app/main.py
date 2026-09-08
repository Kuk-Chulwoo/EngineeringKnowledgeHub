from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .ai.config import ProviderPolicy
from .config import Settings
from .database import Database
from .engineering.auth import LocalReviewer
from .engineering.repository import EngineeringRepository
from .engineering.routes import router as engineering_router
from .engineering.service import EngineeringService
from .repository import Repository
from .routes import router
from .services import HubService, ServiceError
from .storage import LocalStorage, Storage


class BodyLimitMiddleware:
    """Bound the complete multipart body before the parser can spool unlimited data."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        consumed = 0
        exceeded = False

        async def limited_receive():
            nonlocal consumed, exceeded
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > self.max_bytes:
                exceeded = True
                from starlette.exceptions import HTTPException

                raise HTTPException(413, "Request body exceeds upload limit")
            return message

        async def limited_send(message):
            # The multipart parser may convert receive exceptions to HTTP 400.
            if exceeded and message["type"] == "http.response.start":
                message["status"] = 413
            await send(message)

        await self.app(scope, limited_receive, limited_send)


def create_app(settings: Settings | None = None, storage: Storage | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield

    app = FastAPI(title="Engineering Knowledge Hub", version="0.1.0", lifespan=lifespan)
    app.state.service = HubService(
        Repository(database),
        storage or LocalStorage(settings.storage_root),
        settings.max_upload_bytes,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_upload_bytes + 1024 * 1024)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"detail": error.detail})

    app.state.engineering = EngineeringService(EngineeringRepository(database), app.state.service, ProviderPolicy.from_env())
    app.state.reviewer = LocalReviewer(settings.reviewer_file)
    app.include_router(engineering_router)
    app.include_router(router)
    return app


app = create_app()
