import pytest
from pyproj import CRS, Geod
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box

from app.models import MeasurementStatus as S
from app.services.crs import crs_label, utm_epsg
from app.services.measurements import Measurer

GEOD = Geod(ellps="WGS84")
WGS84 = CRS.from_epsg(4326)


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [
        (78.4, 17.4, 32644),    # Hyderabad
        (-0.1, 51.5, 32630),    # London
        (-70.0, -33.0, 32719),  # Santiago, southern hemisphere
        (179.9, 0.0, 32660),    # last zone
        (-179.9, 0.0, 32601),   # first zone
        (10.0, 88.0, 32661),    # UPS north
        (10.0, -85.0, 32761),   # UPS south
    ],
)
def test_utm_epsg(lon, lat, epsg):
    assert utm_epsg(lon, lat) == epsg


def test_crs_label():
    assert crs_label(WGS84) == "EPSG:4326"


def test_polygon_area_matches_geodesic_and_is_not_in_degrees():
    poly = box(78.40, 17.40, 78.41, 17.41)
    m = Measurer().measure(poly, WGS84)
    ref = abs(GEOD.geometry_area_perimeter(poly)[0])
    assert m.status == S.OK and m.projected_crs == "EPSG:32644"
    assert m.area_m2 == pytest.approx(ref, rel=0.003)
    assert m.area_m2 > 1e6  # ~1.2 km², not 0.0001 "square degrees"


def test_line_length_matches_geodesic():
    line = LineString([(78.40, 17.40), (78.42, 17.40)])
    m = Measurer().measure(line, WGS84)
    assert m.length_m == pytest.approx(GEOD.geometry_length(line), rel=0.002)


def test_web_mercator_input_is_not_trusted():
    line = LineString([(78.40, 17.40), (78.42, 17.40)])
    merc = CRS.from_epsg(3857)
    from pyproj import Transformer
    t = Transformer.from_crs(WGS84, merc, always_xy=True)
    from shapely.ops import transform
    line_m = transform(t.transform, line)
    assert line_m.length > GEOD.geometry_length(line) * 1.04  # naive metres are ~4.6% too long
    m = Measurer().measure(line_m, merc)
    assert m.length_m == pytest.approx(GEOD.geometry_length(line), rel=0.002)


def test_point_not_applicable():
    assert Measurer().measure(Point(1, 1), WGS84).status == S.NOT_APPLICABLE


def test_geometry_collection_unsupported_not_crash():
    gc = GeometryCollection([Point(78.4, 17.4), LineString([(78.4, 17.4), (78.5, 17.4)])])
    m = Measurer().measure(gc, WGS84)
    assert m.status == S.UNSUPPORTED and "GeometryCollection" in m.message


def test_empty_and_none_skipped():
    assert Measurer().measure(None, WGS84).status == S.SKIPPED
    assert Measurer().measure(Polygon(), WGS84).status == S.SKIPPED


def test_invalid_polygon_is_flagged():
    bowtie = Polygon([(78.40, 17.40), (78.41, 17.41), (78.41, 17.40), (78.40, 17.41)])
    m = Measurer().measure(bowtie, WGS84)
    assert m.status == S.OK and "invalid" in m.message


def test_out_of_range_coordinates_give_error_status():
    m = Measurer().measure(LineString([(10, 95), (11, 96)]), WGS84)
    assert m.status == S.ERROR
