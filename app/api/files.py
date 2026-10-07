from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import EmptyUpload, ProcessingError, UploadTooLarge
from app.models import Feature, FileStatus, MeasurementStatus, UploadedFile
from app.schemas import (
    FeatureOut,
    FeaturePage,
    FileInfo,
    MeasurementOut,
    MeasurementPage,
    MeasurementSummary,
)
from app.services.archive import save_upload
from app.services.processor import process_file

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXTENSIONS = {".zip": "shapefile", ".kml": "kml"}


def get_db(request: Request):
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def _get_record(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(404, detail=f"File {file_id!r} not found")
    return record


def _require_completed(record: UploadedFile) -> None:
    if record.status != FileStatus.COMPLETED:
        raise HTTPException(
            409,
            detail={
                "message": f"File is not ready (status: {record.status})",
                "status": record.status,
                "error": record.error,
            },
        )


def _file_info(db: Session, record: UploadedFile) -> FileInfo:
    counts = db.execute(
        select(Feature.geometry_type, func.count())
        .where(Feature.file_id == record.id)
        .group_by(Feature.geometry_type)
    ).all()
    return FileInfo(
        id=record.id,
        filename=record.filename,
        file_type=record.file_type,
        feature_count=record.feature_count,
        crs=record.crs,
        status=record.status,
        error=record.error,
        created_at=record.created_at,
        geometry_type_counts=dict(counts),
    )


@router.post("/", response_model=FileInfo, status_code=201, summary="Upload and process a file")
def upload_file(
    request: Request,
    file: UploadFile = File(..., description="A .kml file, or a .zip containing a Shapefile"),
    default_crs: str | None = Form(
        None,
        description="CRS to assume for a Shapefile that has no .prj (e.g. 'EPSG:4326'). Ignored for KML.",
    ),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, detail="Unsupported file type. Upload a .kml or a .zip containing a Shapefile.")

    with tempfile.TemporaryDirectory(prefix="geoupload-") as tmp:
        saved = Path(tmp) / f"upload{ext}"
        try:
            save_upload(file, saved, settings.max_upload_bytes)
        except UploadTooLarge:
            raise HTTPException(413, detail=f"File exceeds the {settings.max_upload_bytes // 2**20} MB limit")
        except EmptyUpload:
            raise HTTPException(400, detail="Uploaded file is empty")

        record = UploadedFile(filename=filename, file_type=ALLOWED_EXTENSIONS[ext])
        db.add(record)
        db.commit()

        try:
            process_file(db, record, saved, settings, default_crs)
        except ProcessingError as exc:
            raise HTTPException(
                422, detail={"id": record.id, "status": FileStatus.FAILED, "error": str(exc)}
            )
        except Exception:
            raise HTTPException(500, detail={"id": record.id, "status": FileStatus.FAILED, "error": "Internal error"})

    return _file_info(db, record)


@router.get("/{file_id}/", response_model=FileInfo, summary="File information")
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _file_info(db, _get_record(db, file_id))


@router.get("/{file_id}/features/", response_model=FeaturePage, summary="Extracted features")
def list_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    geometry_type: str | None = Query(None, description="Filter, e.g. Polygon"),
    db: Session = Depends(get_db),
):
    _require_completed(_get_record(db, file_id))
    query = select(Feature).where(Feature.file_id == file_id)
    if geometry_type:
        query = query.where(Feature.geometry_type == geometry_type)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Feature.index).limit(limit).offset(offset)).all()
    return FeaturePage(
        file_id=file_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[
            FeatureOut(
                index=r.index,
                layer=r.layer,
                geometry_type=r.geometry_type,
                crs=r.crs,
                geometry=r.geometry,
                properties=r.properties,
            )
            for r in rows
        ],
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementPage, summary="Feature measurements")
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    geometry_type: str | None = Query(None, description="Filter, e.g. Polygon"),
    db: Session = Depends(get_db),
):
    _require_completed(_get_record(db, file_id))

    # Summary covers the whole file, independent of pagination / filtering.
    total_area, total_length = db.execute(
        select(func.coalesce(func.sum(Feature.area_m2), 0.0), func.coalesce(func.sum(Feature.length_m), 0.0))
        .where(Feature.file_id == file_id, Feature.measurement_status == MeasurementStatus.OK)
    ).one()
    status_counts = dict(
        db.execute(
            select(Feature.measurement_status, func.count())
            .where(Feature.file_id == file_id)
            .group_by(Feature.measurement_status)
        ).all()
    )

    query = select(Feature).where(Feature.file_id == file_id)
    if geometry_type:
        query = query.where(Feature.geometry_type == geometry_type)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Feature.index).limit(limit).offset(offset)).all()

    return MeasurementPage(
        file_id=file_id,
        total=total,
        limit=limit,
        offset=offset,
        summary=MeasurementSummary(
            total_area_m2=round(total_area, 6),
            total_length_m=round(total_length, 6),
            status_counts=status_counts,
        ),
        items=[
            MeasurementOut(
                feature_index=r.index,
                layer=r.layer,
                geometry_type=r.geometry_type,
                status=r.measurement_status,
                area_m2=r.area_m2,
                length_m=r.length_m,
                projected_crs=r.measurement_crs,
                message=r.measurement_message,
            )
            for r in rows
        ],
    )
