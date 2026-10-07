"""Orchestrates: parse file -> measure every feature -> persist."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ProcessingError
from app.models import Feature, FileStatus, UploadedFile
from app.services.crs import crs_label
from app.services.ingest import parse_crs, read_features
from app.services.measurements import Measurer

log = logging.getLogger(__name__)


def process_file(
    db: Session,
    record: UploadedFile,
    saved_path: Path,
    settings: Settings,
    default_crs: str | None = None,
) -> None:
    """Fill `record` and its features. On failure the record is marked FAILED and the
    exception is re-raised so the API layer can map it to an HTTP status."""
    try:
        parsed = read_features(
            saved_path,
            record.file_type,
            
             parse_crs(default_crs) if record.file_type == "shapefile" else None,
            max_members=settings.max_zip_members,
            max_bytes=settings.max_uncompressed_bytes,
        )
        if not parsed:
            raise ProcessingError("The file contains no features")

        measurer = Measurer()
        rows: list[Feature] = []
        labels: set[str] = set()
        for pf in parsed:
            label = crs_label(pf.crs)
            labels.add(label)
            m = measurer.measure(pf.geometry, pf.crs)
            rows.append(
                Feature(
                    file_id=record.id,
                    index=pf.index,
                    layer=pf.layer,
                    geometry_type=pf.geometry.geom_type if pf.geometry is not None else "None",
                    geometry=pf.geometry_json,
                    crs=label,
                    properties=pf.properties,
                    measurement_status=m.status,
                    area_m2=m.area_m2,
                    length_m=m.length_m,
                    measurement_crs=m.projected_crs,
                    measurement_message=m.message,
                )
            )

        db.add_all(rows)
        record.feature_count = len(rows)
        record.crs = labels.pop() if len(labels) == 1 else "MIXED"
        record.status = FileStatus.COMPLETED
        db.commit()
    except ProcessingError as exc:
        db.rollback()
        record.status, record.error = FileStatus.FAILED, str(exc)
        db.commit()
        raise
    except Exception:
        log.exception("Unexpected failure while processing %s", record.id)
        db.rollback()
        record.status, record.error = FileStatus.FAILED, "Unexpected error while processing the file"
        db.commit()
        raise
