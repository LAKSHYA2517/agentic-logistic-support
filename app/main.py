"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.logging_config import configure_logging
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
app.include_router(webhook_router)


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
