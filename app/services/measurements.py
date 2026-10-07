"""Area / length calculation in a projected CRS.

Strategy
--------
Measurements are never computed in degrees. For every feature we:
  1. find its centroid and convert it to WGS84 lon/lat,
  2. pick the WGS84 UTM zone (or UPS near the poles) containing that centroid,
  3. reproject the geometry from its source CRS into that zone (units: metres),
  4. read area / length off the projected geometry.

This is done for *every* input CRS, including projected ones: an input such as
Web Mercator (EPSG:3857) is metric but badly distorted away from the equator, so
"it is already projected" does not mean "it is safe to measure".
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pyproj import CRS, Transformer
from shapely import force_2d
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from app.models import MeasurementStatus as S
from app.services.crs import utm_epsg

POINT_TYPES = {"Point", "MultiPoint"}
POLYGON_TYPES = {"Polygon", "MultiPolygon"}
LINE_TYPES = {"LineString", "MultiLineString", "LinearRing"}


@dataclass
class Measurement:
    status: str
    area_m2: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None
    message: str | None = None


class Measurer:
    """Caches pyproj Transformers. Create one per upload: Transformers are not
    guaranteed thread-safe, so the cache is deliberately not global."""

    def __init__(self) -> None:
        self._transformers: dict[tuple[CRS, int], Transformer] = {}

    def _transformer(self, src: CRS, dst_epsg: int) -> Transformer:
        key = (src, dst_epsg)
        if key not in self._transformers:
            self._transformers[key] = Transformer.from_crs(
                src, CRS.from_epsg(dst_epsg), always_xy=True
            )
        return self._transformers[key]

    def _projected_epsg(self, geom: BaseGeometry, src: CRS) -> int:
        c = geom.centroid
        lon, lat = self._transformer(src, 4326).transform(c.x, c.y)
        if not (math.isfinite(lon) and math.isfinite(lat)) or abs(lat) > 90:
            raise ValueError("coordinates are outside the valid range for the file's CRS")
        return utm_epsg(lon, lat)

    def measure(self, geom: BaseGeometry | None, src: CRS) -> Measurement:
        if geom is None or geom.is_empty:
            return Measurement(S.SKIPPED, message="Empty or missing geometry")

        gtype = geom.geom_type
        if gtype in POINT_TYPES:
            return Measurement(S.NOT_APPLICABLE, message="No measurement defined for points")
        if gtype in POLYGON_TYPES:
            kind = "area"
        elif gtype in LINE_TYPES:
            kind = "length"
        else:
            return Measurement(S.UNSUPPORTED, message=f"Measurement is not supported for {gtype}")

        try:
            epsg = self._projected_epsg(geom, src)
            projected = transform(self._transformer(src, epsg).transform, force_2d(geom))
            value = projected.area if kind == "area" else projected.length
            if not math.isfinite(value):
                raise ValueError("projection produced non-finite coordinates")
        except Exception as exc:  # one bad feature must never fail the whole upload
            return Measurement(S.ERROR, message=f"Could not measure geometry: {exc}")

        message = None
        if not geom.is_valid:
            message = "Geometry is invalid (e.g. self-intersecting); result may be unreliable"
        value = round(value, 6)
        return Measurement(
            S.OK,
            area_m2=value if kind == "area" else None,
            length_m=value if kind == "length" else None,
            projected_crs=f"EPSG:{epsg}",
            message=message,
        )
