`# Geospatial File Measurement API

*Author: Saidatta Dasari *

A FastAPI backend that accepts a **Shapefile (`.zip`)** or **KML**, extracts every feature
(index, geometry type, geometry, CRS, properties) and returns **area** for polygons and
**length** for lines. Measurements are always computed in a projected CRS (UTM), never in degrees.

## Quick start

Requires Python 3.11+ (GDAL/PROJ come bundled in the pip wheels).

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .\.venv\Scripts\Activate.ps1)
# source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload
```

- Interactive docs: <http://127.0.0.1:8000/docs>
- Tests: `pytest`
- Docker: `docker build -t geo-api . && docker run -p 8000:8000 geo-api`

Sample files to try are in `samples/` (if present): `survey.kml`, `plots_shapefile.zip`.

<details>
<summary>Configuration (optional environment variables)</summary>

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/geo.db` | Any SQLAlchemy URL |
| `MAX_UPLOAD_MB` | `50` | Max upload size |
| `MAX_UNCOMPRESSED_MB` | `200` | Zip-bomb limit after extraction |
| `MAX_ZIP_MEMBERS` | `200` | Max files inside a zip |

</details>

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/files/` | Upload and process a `.kml` or Shapefile `.zip` |
| `GET /api/files/{id}/` | File info: filename, feature count, CRS, status |
| `GET /api/files/{id}/measurements/` | Per-feature area/length plus totals |
| `GET /api/files/{id}/features/` | Extracted geometry, CRS and properties |
| `GET /health` | Liveness check |

List endpoints take `limit`, `offset` and `geometry_type` query parameters.
`POST` also accepts an optional `default_crs` form field (e.g. `EPSG:4326`) for Shapefiles with no `.prj`.

```bash
curl -F "file=@survey.kml" http://127.0.0.1:8000/api/files/
curl http://127.0.0.1:8000/api/files/<id>/measurements/
```

<details>
<summary>Example: upload response</summary>

```json
{
  "id": "ed26099b1d96440ebd5c14def1c210ee",
  "filename": "survey.kml",
  "file_type": "kml",
  "feature_count": 4,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "geometry_type_counts": {"GeometryCollection": 1, "LineString": 1, "Point": 1, "Polygon": 1}
}
```

</details>

<details>
<summary>Example: measurements response</summary>

```json
{
  "total": 4,
  "summary": {
    "total_area_m2": 1177227.680307,
    "total_length_m": 2126.286974,
    "status_counts": {"NOT_APPLICABLE": 1, "OK": 2, "UNSUPPORTED": 1}
  },
  "items": [
    {"feature_index": 0, "geometry_type": "Polygon", "status": "OK",
     "area_m2": 1177227.680307, "projected_crs": "EPSG:32644"},
    {"feature_index": 1, "geometry_type": "LineString", "status": "OK",
     "length_m": 2126.286974, "projected_crs": "EPSG:32644"},
    {"feature_index": 2, "geometry_type": "Point", "status": "NOT_APPLICABLE"},
    {"feature_index": 3, "geometry_type": "GeometryCollection", "status": "UNSUPPORTED",
     "message": "Measurement is not supported for GeometryCollection"}
  ]
}
```

(Trimmed; the real response also includes `layer`, `file_id`, paging fields and null values.)

</details>

<details>
<summary>Error responses</summary>

| Code | When |
|---|---|
| 415 | Extension is not `.kml` or `.zip` |
| 413 | File larger than the limit |
| 400 | Empty file |
| 422 | Unreadable or invalid content. A `FAILED` record is stored and the body has its `id` and `error` |
| 409 | Measurements/features requested for a file that is not `COMPLETED` |
| 404 | Unknown file id |

</details>

## Architecture

```
app/
  main.py            app factory
  config.py          settings from env vars
  models.py          UploadedFile, Feature tables
  schemas.py         response models
  api/files.py       HTTP layer only (validation, status codes, paging)
  services/
    archive.py       safe upload saving and ZIP extraction
    ingest.py        Shapefile/KML -> features (via GDAL / pyogrio)
    crs.py           CRS labels, UTM zone selection
    measurements.py  reproject + area/length
    processor.py     ingest -> measure -> persist
tests/               unit tests + API tests
```

**File-processing flow**

1. Validate the extension and stream the upload to a temp folder with a size cap.
2. Create a file record with status `PROCESSING`.
3. Shapefile: extract the zip safely, then read every `.shp`. KML: read directly. All layers are read.
4. Read geometry, CRS and attributes with GDAL; make properties JSON-safe.
5. Measure every feature, then save all rows in one transaction.
6. Mark the file `COMPLETED`, or `FAILED` with an error message.

**Measurement flow**

| Geometry | Result |
|---|---|
| Polygon / MultiPolygon | `area_m2` |
| LineString / MultiLineString | `length_m` |
| Point / MultiPoint | `NOT_APPLICABLE` |
| GeometryCollection, others | `UNSUPPORTED` (reported, no crash) |
| Empty or missing | `SKIPPED` |

A failure on one feature is caught and reported as `ERROR` for that feature only.
Invalid polygons are still measured and carry a warning message.

**CRS handling**

- The CRS is read from the file (`.prj`, or WGS84 for KML) and stored per feature.
- For each feature: centroid → WGS84 → matching **UTM zone** → reproject → read area/length.
  The zone used is returned as `projected_crs`.
- Every input CRS is reprojected, including already-projected ones (Web Mercator is metric but distorted).
- A Shapefile with no `.prj` is rejected clearly, unless the client sends `default_crs`.
- Accuracy is checked in tests against geodesic area/length (within 0.3% area, 0.2% length).

## Design decisions

- **FastAPI, not Django:** small stateless API; typed models and auto docs with little code.
- **GDAL via pyogrio/GeoPandas:** one reader for both formats, handles multiple layers; wheels bundle GDAL.
- **UTM per feature:** standard, conformal, and the EPSG code is easy to audit. Alternatives considered: equal-area projection (exact area, odd codes) and pure geodesic maths (most accurate, but the brief asks for projected CRS).
- **Synchronous processing:** simple contract for typical file sizes; the `PROCESSING`/`FAILED` states make a move to background workers easy.
- **Features stored in the DB:** cheap paging and SQL totals without re-parsing files. SQLite by default; any SQLAlchemy DB works.
- **Failed uploads are stored as `FAILED`:** clients can always look up what went wrong.
- **Upload safety:** size limits, zip-slip and zip-bomb protection, only `.kml`/`.zip` accepted.
- **Known limitation:** a feature spanning several UTM zones or crossing the antimeridian is measured in its centroid's zone, so accuracy drops.

## Learning

- A projected CRS is not automatically safe for measuring (Web Mercator inflated a test length by about 4.6%).
- GDAL's KML driver makes each folder a layer and turns mixed `MultiGeometry` into `GeometryCollection`, so reading only the first layer loses data.
- Upload endpoints need defensive ZIP handling (path traversal, zip bombs).
- Testing against an independent geodesic reference is more convincing than hard-coded numbers.
- * On Windows, `pyogrio` failed with "GDAL DLL could not be found" until I reinstalled it from binary wheels in a clean virtual environment.
- Swagger pre-fills optional fields with the text `string`, which got sent as a real `default_crs` value and caused an unexpected 422. I fixed it so the field is ignored    for KML.*

## Future scope

- Background processing (Celery/RQ) with polling or webhooks for large files.
- More formats: GeoJSON, GeoPackage, KMZ.
- Split features across UTM zones, or use equal-area for polygons; optional geodesic cross-check.
- Return geometry in WGS84 on request; add bounding boxes and perimeter.
- PostGIS storage for spatial queries, plus migrations.
- Authentication, per-user files, rate limits, cleanup of old records.
