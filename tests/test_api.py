import io
import zipfile

import geopandas as gpd
import pytest
from pyproj import Geod
from shapely.geometry import LineString, box

from tests.conftest import zip_shapefile

GEOD = Geod(ellps="WGS84")


def upload(client, name, data, **form):
    return client.post("/api/files/", files={"file": (name, data)}, data=form)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_kml_end_to_end(client, kml_bytes):
    r = upload(client, "survey.kml", kml_bytes)
    assert r.status_code == 201, r.text
    info = r.json()
    assert info["status"] == "COMPLETED"
    assert info["crs"] == "EPSG:4326"
    assert info["feature_count"] == 4
    assert info["geometry_type_counts"]["Polygon"] == 1

    assert client.get(f"/api/files/{info['id']}/").json()["filename"] == "survey.kml"

    feats = client.get(f"/api/files/{info['id']}/features/").json()
    poly = next(f for f in feats["items"] if f["geometry_type"] == "Polygon")
    assert poly["crs"] == "EPSG:4326"
    assert poly["geometry"]["type"] == "Polygon"
    assert poly["properties"]["Name"] == "Plot A"

    meas = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_type = {m["geometry_type"]: m for m in meas["items"]}
    ref_area = abs(GEOD.geometry_area_perimeter(box(78.40, 17.40, 78.41, 17.41))[0])
    assert by_type["Polygon"]["area_m2"] == pytest.approx(ref_area, rel=0.003)
    assert by_type["LineString"]["length_m"] == pytest.approx(
        GEOD.geometry_length(LineString([(78.40, 17.40), (78.42, 17.40)])), rel=0.002
    )
    assert by_type["Point"]["status"] == "NOT_APPLICABLE"
    assert by_type["GeometryCollection"]["status"] == "UNSUPPORTED"
    assert meas["summary"]["status_counts"]["OK"] == 2
    assert meas["summary"]["total_area_m2"] == pytest.approx(by_type["Polygon"]["area_m2"])


def test_shapefile_polygons(client, tmp_path):
    gdf = gpd.GeoDataFrame(
        {"name": ["a", "b"], "n": [1, None]},
        geometry=[box(78.40, 17.40, 78.41, 17.41), box(78.50, 17.40, 78.51, 17.41)],
        crs=4326,
    )
    r = upload(client, "plots.zip", zip_shapefile(gdf, tmp_path))
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    feats = client.get(f"/api/files/{fid}/features/").json()["items"]
    assert [f["properties"]["name"] for f in feats] == ["a", "b"]
    assert feats[1]["properties"]["n"] is None
    meas = client.get(f"/api/files/{fid}/measurements/").json()
    assert all(m["status"] == "OK" and m["projected_crs"] == "EPSG:32644" for m in meas["items"])


def test_shapefile_in_web_mercator(client, tmp_path):
    line = LineString([(78.40, 17.40), (78.42, 17.40)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[line], crs=4326).to_crs(3857)
    r = upload(client, "road.zip", zip_shapefile(gdf, tmp_path))
    assert r.status_code == 201, r.text
    assert r.json()["crs"] == "EPSG:3857"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["items"][0]
    assert m["length_m"] == pytest.approx(GEOD.geometry_length(line), rel=0.002)


def test_shapefile_without_prj_fails_cleanly_then_default_crs_works(client, tmp_path):
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[box(78.4, 17.4, 78.41, 17.41)], crs=4326)
    data = zip_shapefile(gdf, tmp_path, drop_ext=(".prj",))
    r = upload(client, "noprj.zip", data)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["status"] == "FAILED" and "no CRS" in detail["error"]
    # the failed upload is still inspectable, and its data endpoints refuse with 409
    assert client.get(f"/api/files/{detail['id']}/").json()["status"] == "FAILED"
    assert client.get(f"/api/files/{detail['id']}/measurements/").status_code == 409

    r = upload(client, "noprj.zip", data, default_crs="EPSG:4326")
    assert r.status_code == 201 and r.json()["crs"] == "EPSG:4326"


def test_pagination_and_filter(client, kml_bytes):
    fid = upload(client, "s.kml", kml_bytes).json()["id"]
    page = client.get(f"/api/files/{fid}/measurements/", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 4 and [i["feature_index"] for i in page["items"]] == [1, 2]
    only = client.get(f"/api/files/{fid}/measurements/", params={"geometry_type": "Polygon"}).json()
    assert only["total"] == 1


def test_rejects_unsupported_extension(client):
    assert upload(client, "x.geojson", b"{}").status_code == 415


def test_rejects_empty_file(client):
    assert upload(client, "x.kml", b"").status_code == 400


def test_rejects_garbage_kml_and_zip(client):
    assert upload(client, "x.kml", b"not xml at all").status_code == 422
    assert upload(client, "x.zip", b"not a zip").status_code == 422


def test_zip_without_shapefile(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "hi")
    r = upload(client, "x.zip", buf.getvalue())
    assert r.status_code == 422 and "No .shp" in r.json()["detail"]["error"]


def test_zip_slip_is_rejected(client, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../evil.shp", "x")
    r = upload(client, "evil.zip", buf.getvalue())
    assert r.status_code == 422 and "Unsafe path" in r.json()["detail"]["error"]


def test_upload_size_limit(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    c = TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path}/s.db", max_upload_bytes=10)))
    assert upload(c, "x.kml", b"x" * 11).status_code == 413


def test_unknown_file_404(client):
    assert client.get("/api/files/nope/").status_code == 404
    assert client.get("/api/files/nope/measurements/").status_code == 404
