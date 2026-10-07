"""Reads Shapefile (zipped) and KML into a flat list of ParsedFeature objects."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pyogrio
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry.base import BaseGeometry

from app.errors import ProcessingError
from app.services.archive import extract_zip
from app.services.crs import WGS84


@dataclass
class ParsedFeature:
    index: int
    layer: str
    geometry: BaseGeometry | None   # shapely object, used for measuring
    geometry_json: dict | None      # GeoJSON-style dict, stored/returned as-is
    crs: CRS
    properties: dict


def parse_crs(value: str | None) -> CRS | None:
    if not value:
        return None
    try:
        return CRS.from_user_input(value)
    except CRSError as exc:
        raise ProcessingError(f"Invalid default_crs {value!r}: {exc}") from exc


def _read_dataset(
    path: Path, *, default_crs: CRS | None, drop_null_props: bool, start_index: int
) -> list[ParsedFeature]:
    """Read every layer of a GDAL-readable dataset (a .shp, or a .kml whose folders are layers)."""
    try:
        layers = pyogrio.list_layers(str(path))
    except Exception as exc:
        raise ProcessingError(f"Could not open {path.name}: {exc}") from exc

    out: list[ParsedFeature] = []
    index = start_index
    for layer_name, _ in layers:
        try:
            gdf = pyogrio.read_dataframe(str(path), layer=str(layer_name))
        except Exception as exc:
            raise ProcessingError(f"Could not read layer {layer_name!r} of {path.name}: {exc}") from exc
        if gdf.empty:
            continue

        crs = gdf.crs or default_crs
        if crs is None:
            raise ProcessingError(
                f"Layer {layer_name!r} has no CRS (is the .prj file missing?). "
                "Add a .prj to the archive or send a `default_crs` form field, e.g. EPSG:4326."
            )

        # GeoDataFrame.to_json gives JSON-safe properties (NaN -> null, timestamps -> ISO strings).
        collection = json.loads(gdf.to_json(na="null", show_bbox=False, drop_id=True))
        for geom, feature in zip(gdf.geometry, collection["features"]):
            props = feature["properties"] or {}
            if drop_null_props:
                props = {k: v for k, v in props.items() if v is not None}
            out.append(
                ParsedFeature(
                    index=index,
                    layer=str(layer_name),
                    geometry=geom,
                    geometry_json=feature["geometry"],
                    crs=crs,
                    properties=props,
                )
            )
            index += 1
    return out


def read_features(
    saved_path: Path, file_type: str, default_crs: CRS | None, *, max_members: int, max_bytes: int
) -> list[ParsedFeature]:
    if file_type == "kml":
        # KML is defined to be WGS84 lon/lat; GDAL reports that, but fall back defensively.
        return _read_dataset(saved_path, default_crs=WGS84, drop_null_props=True, start_index=0)

    extracted = extract_zip(
        saved_path, saved_path.parent / "extracted", max_members=max_members, max_bytes=max_bytes
    )
    shapefiles = sorted(p for p in extracted if p.suffix.lower() == ".shp")
    if not shapefiles:
        raise ProcessingError("No .shp file found inside the ZIP archive")

    features: list[ParsedFeature] = []
    for shp in shapefiles:
        features += _read_dataset(
            shp, default_crs=default_crs, drop_null_props=False, start_index=len(features)
        )
    return features
