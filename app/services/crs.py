"""CRS helpers."""
from __future__ import annotations

from pyproj import CRS

WGS84 = CRS.from_epsg(4326)


def crs_label(crs: CRS) -> str:
    """'EPSG:4326' when the CRS maps to an EPSG code, otherwise its name."""
    try:
        epsg = crs.to_epsg()
    except Exception:  # pragma: no cover - defensive, pyproj can raise on exotic CRS
        epsg = None
    if epsg:
        return f"EPSG:{epsg}"
    return crs.name or "UNKNOWN"


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG code of the WGS84 UTM zone containing (lon, lat).

    North: 32601-32660, South: 32701-32760. UTM is only defined for 80°S–84°N,
    so the polar caps fall back to UPS (32661 north, 32761 south).
    """
    if lat >= 84.0:
        return 32661
    if lat <= -80.0:
        return 32761
    lon = ((lon + 180.0) % 360.0) - 180.0
    zone = min(int((lon + 180.0) // 6) + 1, 60)
    return (32600 if lat >= 0 else 32700) + zone
