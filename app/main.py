"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.logging_config import configure_logging
from app.routes.dashboard import router as dashboard_router
from app.routes.webhook import router as webhook_router
from app.schemas import HealthResponse
from app.seed import seed_demo_drivers
from app.services.meta import prepare_media_directory


settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize local database tables and demo data when the application starts."""

    init_db()
    prepare_media_directory(settings.media_download_dir)
    with SessionLocal() as session:
        seed_demo_drivers(session, settings)
    yield


app = FastAPI(title=settings.name, debug=settings.debug, lifespan=lifespan)

# Allow the Vite dev server (dashboard/) to call the API from a
# different origin. Local dev only -- not a secret, so a fixed
# allow-list is fine rather than new configuration surface.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(dashboard_router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Report whether the API process is running."""

    return HealthResponse()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
