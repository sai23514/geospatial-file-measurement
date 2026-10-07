import io
import zipfile

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>survey</name>
<Placemark><name>Plot A</name><description>demo plot</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
78.40,17.40,0 78.41,17.40,0 78.41,17.41,0 78.40,17.41,0 78.40,17.40,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Road</name><LineString><coordinates>78.40,17.40,0 78.42,17.40,0</coordinates></LineString></Placemark>
<Placemark><name>Pin</name><Point><coordinates>78.4,17.4,0</coordinates></Point></Placemark>
<Placemark><name>Mixed</name><MultiGeometry>
<Point><coordinates>78.4,17.4,0</coordinates></Point>
<LineString><coordinates>78.40,17.40,0 78.42,17.40,0</coordinates></LineString>
</MultiGeometry></Placemark>
</Document></kml>
"""


@pytest.fixture()
def client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/test.db"))
    return TestClient(app)


@pytest.fixture()
def kml_bytes() -> bytes:
    return KML.encode()


def zip_shapefile(gdf: gpd.GeoDataFrame, tmp_path, *, drop_ext: tuple[str, ...] = ()) -> bytes:
    d = tmp_path / "shp"
    d.mkdir(exist_ok=True)
    gdf.to_file(d / "data.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in d.iterdir():
            if p.suffix not in drop_ext:
                z.write(p, p.name)
    return buf.getvalue()
