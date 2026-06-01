"""Utilidades mínimas para AOI y config (Fondecyt PUC)."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import yaml
from shapely.geometry import mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.yaml"


def load_config(path: Path | None = None) -> dict:
    p = path or CONFIG_PATH
    with open(p, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def predio_shapefiles(config: dict) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for pid, pcfg in (config.get("predios") or {}).items():
        rel = pcfg.get("aoi_source")
        if not rel:
            continue
        out[pid] = (REPO_ROOT / rel).resolve()
    return out


def build_master_aoi_geojson(config: dict) -> Path:
    """Fusiona los predios en un GeoJSON para el mapa."""
    rel = config.get("master_aoi_path") or "data/shapefiles/pumahuida_aoi.geojson"
    out_path = (REPO_ROOT / rel).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    id_col = config.get("shapefile_id_col") or "predio_id"
    name_col = config.get("shapefile_name_col") or "nombre"

    features = []
    for pid, shp_path in predio_shapefiles(config).items():
        if not shp_path.is_file():
            continue
        gdf = gpd.read_file(shp_path)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        else:
            gdf = gdf.to_crs("EPSG:4326")
        geom = gdf.union_all()
        pcfg = config["predios"][pid]
        props = {
            id_col: pid,
            name_col: pcfg.get("name") or pid,
            "color": pcfg.get("color"),
        }
        features.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})

    fc = {"type": "FeatureCollection", "features": features}
    out_path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return out_path


def predio_bounds_center(geom) -> tuple[list, list]:
    """``(leaflet_bounds, center [lat, lon])``."""
    minx, miny, maxx, maxy = geom.bounds
    leaflet_bounds = [[miny, minx], [maxy, maxx]]
    center = [(miny + maxy) / 2, (minx + maxx) / 2]
    return leaflet_bounds, center
