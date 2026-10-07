from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        # FastAPI runs sync endpoints in a threadpool, so allow cross-thread use.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" not in url and "///" in url:
            Path(url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, **kwargs)
