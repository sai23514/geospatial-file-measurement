from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy.orm import sessionmaker

from app.api import files
from app.config import Settings, get_settings
from app.database import Base, make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)

    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        description="Upload a Shapefile (.zip) or KML and get per-feature area / length measurements.",
    )
    app.state.settings = settings
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.include_router(files.router)

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app
