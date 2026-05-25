#!/usr/bin/env python3
"""
GeoTIFF semanales (``Y{year}_W{week}.tif``) → series por parcela + WebP para el explorador.

Sin histórico interanual: solo medias semanales por parcela a lo largo del tiempo.

Uso (desde la raíz del repo)::

    python scripts/static_site/build_sentinel2_local.py
    python scripts/static_site/build_sentinel2_local.py --force
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np

warnings_imported = False
try:
    import rasterio
    from rasterio.mask import mask as rio_mask
    from rasterio.warp import transform_bounds
except ImportError as exc:
    print(f"Falta rasterio: {exc}", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image as PILImage
except ImportError as exc:
    print(f"Falta Pillow: {exc}", file=sys.stderr)
    sys.exit(1)

try:
    from matplotlib import colormaps as _MPL_COLORMAPS
except ImportError as exc:
    print(f"Falta matplotlib: {exc}", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__" and not __package__:
    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from scripts.static_site.pipeline_utils import (
    REPO_ROOT,
    build_master_aoi_geojson,
    load_config,
    wetland_bounds_center,
    wetland_shapefiles,
)

_STEM_RE = re.compile(r"^Y(?P<year>\d{4})_W(?P<week>\d{2})$", re.I)

BAND_VIZ: dict[str, dict] = {
    "NDVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlGn", "label": "NDVI"},
    "kNDVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlGn", "label": "kNDVI"},
    "GNDVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "YlGn", "label": "GNDVI"},
    "EVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "YlGn", "label": "EVI"},
    "EVI2": {"vmin": -1.0, "vmax": 1.0, "colormap": "YlGn", "label": "EVI2"},
    "SAVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "YlGn", "label": "SAVI"},
    "MSAVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "YlGn", "label": "MSAVI"},
    "ARVI": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlGn", "label": "ARVI"},
    "NDII": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlBu", "label": "NDII"},
    "NDCI": {"vmin": -1.0, "vmax": 1.0, "colormap": "YlGn", "label": "NDCI"},
    "NDWI": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlBu", "label": "NDWI"},
    "MNDWI": {"vmin": -1.0, "vmax": 1.0, "colormap": "Blues", "label": "MNDWI"},
    "NDMI": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlBu_r", "label": "NDMI"},
    "NDMISTRESS": {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlBu_r", "label": "NDMI stress"},
    "MSI": {"vmin": 0.0, "vmax": 3.0, "colormap": "RdYlBu_r", "label": "MSI"},
    "ARI": {"vmin": 0.0, "vmax": 2.0, "colormap": "RdPu", "label": "ARI"},
    "MARI": {"vmin": 0.0, "vmax": 4.0, "colormap": "RdPu", "label": "MARI"},
    "MCARI": {"vmin": 0.0, "vmax": 3.0, "colormap": "YlGn", "label": "MCARI"},
    "CHL_REDEDGE": {"vmin": 0.0, "vmax": 3.0, "colormap": "YlGn", "label": "Chl rededge"},
    "PSSRB1": {"vmin": 0.0, "vmax": 10.0, "colormap": "viridis", "label": "PSSRB1"},
    "SIPI1": {"vmin": 0.0, "vmax": 2.0, "colormap": "RdYlGn_r", "label": "SIPI1"},
    "PSRI": {"vmin": -0.5, "vmax": 0.5, "colormap": "RdYlGn_r", "label": "PSRI"},
    "LAI": {"vmin": 0.0, "vmax": 8.0, "colormap": "YlGn", "label": "LAI"},
    "FAPAR": {"vmin": 0.0, "vmax": 1.0, "colormap": "YlGn", "label": "FAPAR"},
    "FCOVER": {"vmin": 0.0, "vmax": 1.0, "colormap": "YlGn", "label": "FCOVER"},
    "LEAF_CHL": {"vmin": 0.0, "vmax": 80.0, "colormap": "YlGn", "label": "Leaf chlorophyll"},
    "CANOPY_CHL": {"vmin": 0.0, "vmax": 600.0, "colormap": "YlGn", "label": "Canopy chlorophyll"},
    "CLEAR_PIXEL_COUNT": {"vmin": 0.0, "vmax": 30.0, "colormap": "viridis", "label": "Clear pixels"},
}
DEFAULT_VIZ = {"vmin": -1.0, "vmax": 1.0, "colormap": "RdYlGn", "label": ""}
SKIP_BANDS = {"REDEDGE_POSITION"}
SENTINEL_VALUES = (32767.0, -32767.0, 32768.0, -32768.0)
DIVISOR_DEFAULT = 100.0
BAND_DIVISOR_OVERRIDE = {"CLEAR_PIXEL_COUNT": 1.0}
WEBP_QUALITY = 86
WEBP_UPSCALE_MIN_SIDE = 384


def discover_weekly_tifs(tif_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(tif_dir.glob("Y*_W*.tif")):
        m = _STEM_RE.match(path.stem)
        if not m:
            continue
        y, w = int(m.group("year")), int(m.group("week"))
        try:
            date.fromisocalendar(y, w, 4)
        except ValueError:
            continue
        rows.append(
            {
                "path": path,
                "year": y,
                "week": w,
                "key": f"{y}_w{w:02d}",
                "label": f"{y} · S{w:02d}",
            }
        )
    rows.sort(key=lambda r: (r["year"], r["week"]))
    return rows


def load_parcel_geoms(config: dict) -> dict[str, dict]:
    """``{wetland_id: {geometry, bounds, center, name, color}}``."""
    parcels: dict[str, dict] = {}
    for wid, shp_path in wetland_shapefiles(config).items():
        if not shp_path.is_file():
            raise FileNotFoundError(f"Falta shapefile: {shp_path}")
        gdf = gpd.read_file(shp_path)
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        else:
            gdf = gdf.to_crs("EPSG:4326")
        geom = gdf.unary_union
        bounds, center = wetland_bounds_center(geom)
        wcfg = config["wetlands"][wid]
        parcels[wid] = {
            "geometry": geom,
            "geojson": json.loads(gpd.GeoSeries([geom], crs="EPSG:4326").to_json())["features"][0][
                "geometry"
            ],
            "leaflet_bounds": bounds,
            "center": center,
            "name": wcfg.get("name") or wid,
            "color": wcfg.get("color") or "#1d6b4a",
        }
    return parcels


def _sanitize(v: float | None) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(float(v), 4)


def _read_bands_normalized(ds) -> tuple[np.ndarray, list[str]]:
    band_names = [
        (b or f"B{i+1}").strip().upper()
        for i, b in enumerate(ds.descriptions or [])
    ]
    if not band_names:
        band_names = [f"B{i+1}" for i in range(ds.count)]
    arr = ds.read().astype(np.float32, copy=False)
    if ds.nodata is not None:
        arr = np.where(arr == ds.nodata, np.nan, arr)
    for sentinel in SENTINEL_VALUES:
        arr = np.where(arr == sentinel, np.nan, arr)
    divisors = np.array(
        [BAND_DIVISOR_OVERRIDE.get(b, DIVISOR_DEFAULT) for b in band_names],
        dtype=np.float32,
    ).reshape(-1, 1, 1)
    arr = arr / divisors[: arr.shape[0]]
    return arr, band_names


def extract_parcel_means_from_tif(
    tif_path: Path, parcel_geom, band_names_ref: list[str] | None
) -> tuple[dict[str, float | None], list[str], np.ndarray | None]:
    with rasterio.open(tif_path) as ds:
        arr, band_names = _read_bands_normalized(ds)
        if band_names_ref and band_names != band_names_ref:
            pass
        geoms = [parcel_geom.__geo_interface__ if hasattr(parcel_geom, "__geo_interface__") else parcel_geom]
        try:
            clipped, _ = rio_mask(ds, geoms, crop=True, filled=False)
        except ValueError:
            return {b: None for b in band_names if b not in SKIP_BANDS}, band_names, None
        clipped = clipped.astype(np.float32)
        if ds.nodata is not None:
            clipped = np.where(clipped == ds.nodata, np.nan, clipped)
        for sentinel in SENTINEL_VALUES:
            clipped = np.where(clipped == sentinel, np.nan, clipped)
        divisors = np.array(
            [BAND_DIVISOR_OVERRIDE.get(b, DIVISOR_DEFAULT) for b in band_names],
            dtype=np.float32,
        ).reshape(-1, 1, 1)
        clipped = clipped / divisors[: clipped.shape[0]]
        means: dict[str, float | None] = {}
        for i, band in enumerate(band_names):
            if band in SKIP_BANDS:
                continue
            with np.errstate(invalid="ignore"):
                m = float(np.nanmean(clipped[i]))
            means[band] = _sanitize(m) if math.isfinite(m) else None
        return means, band_names, clipped


class ColormapCache:
    def __init__(self) -> None:
        self._luts: dict[str, np.ndarray] = {}

    def get(self, name: str) -> np.ndarray:
        if name not in self._luts:
            try:
                cmap = _MPL_COLORMAPS[name]
            except KeyError:
                cmap = _MPL_COLORMAPS["RdYlGn"]
            self._luts[name] = (cmap(np.linspace(0, 1, 256)) * 255).astype(np.uint8)
        return self._luts[name]


CMAP_CACHE = ColormapCache()

PARCEL_ALL_KEY = "__all__"


def is_normalized_band(band: str) -> bool:
    """Índices con rango teórico negativo–positivo centrados en 0 (p. ej. NDVI, NDWI)."""
    viz = BAND_VIZ.get(band, DEFAULT_VIZ)
    return float(viz["vmin"]) < 0.0 < float(viz["vmax"])


def _stretch_entry_from_percentiles(p0f: float, p100f: float, band: str) -> dict[str, float | bool]:
    viz = BAND_VIZ.get(band, DEFAULT_VIZ)
    if p0f == p100f:
        eps = max(abs(p0f) * 0.02, 1e-4)
        p0f -= eps
        p100f += eps
    entry: dict[str, float | bool] = {
        "p0": round(p0f, 5),
        "p100": round(p100f, 5),
    }
    if is_normalized_band(band):
        center = float(viz.get("center", 0.0))
        spread = max(abs(p0f - center), abs(p100f - center))
        if spread < 1e-9:
            spread = max(abs(center) * 0.02, 1e-4)
        vmin = center - spread
        vmax = center + spread
        entry.update(
            {
                "center": round(center, 5),
                "spread": round(spread, 5),
                "symmetric": True,
                "vmin": round(vmin, 5),
                "vmax": round(vmax, 5),
            }
        )
    else:
        entry.update({"symmetric": False, "vmin": round(p0f, 5), "vmax": round(p100f, 5)})
    return entry


def _accumulate_pixels(acc: dict[tuple[str, str], list[np.ndarray]], wid: str, band: str, data: np.ndarray) -> None:
    flat = data.astype(np.float32, copy=False).ravel()
    flat = flat[np.isfinite(flat)]
    if flat.size == 0:
        return
    acc.setdefault((wid, band), []).append(flat)


def _compute_stretch_limits(
    acc: dict[tuple[str, str], list[np.ndarray]],
    band_names: list[str],
    parcel_ids: list[str],
) -> dict[str, dict[str, dict[str, float]]]:
    """p0 / p100 por parcela × banda (píxeles válidos en todas las semanas)."""
    by_wetland: dict[str, dict[str, dict[str, float]]] = {wid: {} for wid in parcel_ids}
    pooled: dict[str, list[np.ndarray]] = {b: [] for b in band_names if b not in SKIP_BANDS}

    for (wid, band), chunks in acc.items():
        if not chunks:
            continue
        vals = np.concatenate(chunks)
        if vals.size == 0:
            continue
        p0, p100 = np.percentile(vals, [0.0, 100.0])
        p0f, p100f = float(p0), float(p100)
        if not (math.isfinite(p0f) and math.isfinite(p100f)):
            continue
        by_wetland.setdefault(wid, {})[band] = _stretch_entry_from_percentiles(p0f, p100f, band)
        pooled.setdefault(band, []).append(vals)

    all_limits: dict[str, dict[str, float]] = {}
    for band, chunks in pooled.items():
        if not chunks:
            continue
        vals = np.concatenate(chunks)
        p0, p100 = np.percentile(vals, [0.0, 100.0])
        p0f, p100f = float(p0), float(p100)
        if not (math.isfinite(p0f) and math.isfinite(p100f)):
            continue
        all_limits[band] = _stretch_entry_from_percentiles(p0f, p100f, band)
    if all_limits:
        by_wetland[PARCEL_ALL_KEY] = all_limits

    for wid in parcel_ids:
        for band in band_names:
            if band in SKIP_BANDS:
                continue
            if band in by_wetland.get(wid, {}):
                continue
            viz = BAND_VIZ.get(band, DEFAULT_VIZ)
            by_wetland.setdefault(wid, {})[band] = _stretch_entry_from_percentiles(
                float(viz["vmin"]), float(viz["vmax"]), band
            )
    return by_wetland


def stretch_for_render(
    stretch_by_wetland: dict[str, dict[str, dict[str, float]]],
    wid: str,
    band: str,
) -> tuple[float, float]:
    lim = (stretch_by_wetland.get(wid) or {}).get(band)
    if lim:
        return float(lim["vmin"]), float(lim["vmax"])
    viz = BAND_VIZ.get(band, DEFAULT_VIZ)
    return float(viz["vmin"]), float(viz["vmax"])


def render_band_webp(data: np.ndarray, out_path: Path, *, vmin: float, vmax: float, colormap: str) -> None:
    arr = data.astype(np.float32, copy=False)
    mask = ~np.isfinite(arr)
    span = max(float(vmax) - float(vmin), 1e-9)
    norm = np.clip((arr - vmin) / span, 0.0, 1.0)
    norm = np.where(mask, 0.0, norm)
    idx = (norm * 255.0).astype(np.uint8)
    lut = CMAP_CACHE.get(colormap)
    rgba = lut[idx].copy()
    rgba[mask, 3] = 0
    h, w = rgba.shape[:2]
    if min(h, w) < WEBP_UPSCALE_MIN_SIDE:
        scale = WEBP_UPSCALE_MIN_SIDE / max(1, min(h, w))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
    else:
        new_w, new_h = w, h
    img = PILImage.fromarray(rgba, mode="RGBA")
    if (new_w, new_h) != (w, h):
        img = img.resize((new_w, new_h), PILImage.NEAREST)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="WEBP", quality=WEBP_QUALITY, method=4)


def main() -> None:
    parser = argparse.ArgumentParser(description="Construir data_static desde TIF semanales.")
    parser.add_argument("--force", action="store_true", help="Regenerar todos los WebP.")
    args = parser.parse_args()

    config = load_config()
    src_cfg = config["sources"]["sentinel2"]
    tif_dir = (REPO_ROOT / src_cfg["input_root"]).resolve()
    static_dir = (REPO_ROOT / src_cfg["static_root"]).resolve()
    raster_dir = static_dir / "rasters"
    raster_dir.mkdir(parents=True, exist_ok=True)

    records = discover_weekly_tifs(tif_dir)
    if not records:
        print(f"No hay TIF en {tif_dir}", file=sys.stderr)
        sys.exit(1)

    parcels = load_parcel_geoms(config)
    build_master_aoi_geojson(config)
    static_aoi = REPO_ROOT / "data_static" / "wetlands_aoi.geojson"
    static_aoi.parent.mkdir(parents=True, exist_ok=True)
    master = REPO_ROOT / config.get("master_aoi_path", "data/shapefiles/pumahuida_aoi.geojson")
    static_aoi.write_text(master.read_text(encoding="utf-8"), encoding="utf-8")

    parcel_ids = list(parcels.keys())
    timeline = [{"year": r["year"], "week": r["week"], "key": r["key"], "label": r["label"]} for r in records]
    n_t = len(timeline)

    series: dict[str, dict[str, list]] = {}
    band_names: list[str] = []
    rasters_meta: dict[str, dict] = {}
    wetlands_meta: dict[str, dict] = {}
    pixel_acc: dict[tuple[str, str], list[np.ndarray]] = {}

    for wid, pinfo in parcels.items():
        wetlands_meta[wid] = {
            "name": pinfo["name"],
            "color": pinfo["color"],
            "center": pinfo["center"],
            "leaflet_bounds": pinfo["leaflet_bounds"],
        }

    print(f"TIF semanales: {len(records)}  |  Parcelas: {', '.join(parcel_ids)}")
    print("  Paso 1/2: medias temporales + percentiles p0/p100 por parcela…")

    for ti, rec in enumerate(records):
        tif_path = rec["path"]
        print(f"    [{ti+1}/{len(records)}] {tif_path.name}")
        for wid in parcel_ids:
            means, bnames, clipped = extract_parcel_means_from_tif(
                tif_path, parcels[wid]["geometry"], band_names or None
            )
            if not band_names:
                band_names = bnames
            for band, val in means.items():
                series.setdefault(band, {}).setdefault(wid, [None] * n_t)
                series[band][wid][ti] = val

            if clipped is None:
                continue
            for bi, band in enumerate(bnames):
                if band in SKIP_BANDS:
                    continue
                _accumulate_pixels(pixel_acc, wid, band, clipped[bi])

    stretch_by_wetland = _compute_stretch_limits(pixel_acc, band_names, parcel_ids)
    print("  Paso 2/2: WebP con paletas estiradas a p0–p100…")

    for ti, rec in enumerate(records):
        tif_path = rec["path"]
        print(f"    [{ti+1}/{len(records)}] {tif_path.name}")
        for wid in parcel_ids:
            _, bnames, clipped = extract_parcel_means_from_tif(
                tif_path, parcels[wid]["geometry"], band_names or None
            )
            if clipped is None:
                continue
            for bi, band in enumerate(bnames):
                if band in SKIP_BANDS:
                    continue
                viz = BAND_VIZ.get(band, DEFAULT_VIZ)
                vmin, vmax = stretch_for_render(stretch_by_wetland, wid, band)
                stem = f"{wid}_{rec['key']}_{band.lower()}"
                rel = f"sentinel2/rasters/{stem}.webp"
                out_webp = static_dir / "rasters" / f"{stem}.webp"
                if args.force or not out_webp.is_file():
                    render_band_webp(
                        clipped[bi],
                        out_webp,
                        vmin=vmin,
                        vmax=vmax,
                        colormap=viz["colormap"],
                    )
                rasters_meta[f"{wid}_{rec['key']}_{band.lower()}"] = {
                    "p": rel,
                    "l": f"{pinfo['name'] if (pinfo := parcels[wid]) else wid} · {rec['label']} · {viz.get('label', band)}",
                    "year": rec["year"],
                    "week": rec["week"],
                    "wetland_id": wid,
                    "band": band,
                    "vmin": vmin,
                    "vmax": vmax,
                    "colormap": viz["colormap"],
                }

    indices_meta = {}
    for band in band_names:
        if band in SKIP_BANDS:
            continue
        viz = BAND_VIZ.get(band, DEFAULT_VIZ)
        norm = is_normalized_band(band)
        indices_meta[band] = {
            "label": viz.get("label") or band,
            "colormap": viz["colormap"],
            "symmetric": norm,
            "center": float(viz.get("center", 0.0)) if norm else None,
            "fallback_vmin": viz["vmin"],
            "fallback_vmax": viz["vmax"],
        }

    last_key = timeline[-1]["key"] if timeline else None
    ts_payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "default_band": "NDVI" if "NDVI" in series else next(iter(series), "NDVI"),
        "timeline": timeline,
        "series": series,
        "wetlands": wetlands_meta,
        "indices": indices_meta,
        "last_timeline_key": last_key,
    }
    meta_payload = {
        "generated_at": ts_payload["generated_at"],
        "default_band": ts_payload["default_band"],
        "indices": indices_meta,
        "wetlands": wetlands_meta,
        "timeline": timeline,
        "last_timeline_key": last_key,
        "rasters": rasters_meta,
        "stretch_by_wetland": stretch_by_wetland,
        "view_modes": {
            "weekly": {
                "label": "Semanal",
                "template": "{wetland_id}_{year}_w{week:02d}_{band}",
            }
        },
    }

    (static_dir / "timeseries.json").write_text(
        json.dumps(ts_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (static_dir / "metadata.json").write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_path = REPO_ROOT / "data_static" / "sources_manifest.json"
    drone_cfg = config.get("sources", {}).get("drone", {})
    drone_static = (REPO_ROOT / drone_cfg.get("static_root", "data_static/drone")).resolve()
    drone_has = (drone_static / "metadata.json").is_file()

    manifest = {
        "generated_at": ts_payload["generated_at"],
        "aoi_path": "wetlands_aoi.geojson",
        "project_title": "Pumahuida · Fondecyt PUC",
        "sources": {
            "sentinel2": {
                "id": "sentinel2",
                "label": src_cfg.get("label", "Sentinel-2"),
                "has_data": True,
                "timeseries_path": "sentinel2/timeseries.json",
                "metadata_path": "sentinel2/metadata.json",
                "status": "ready",
            },
            "drone": {
                "id": "drone",
                "label": drone_cfg.get("label", "Dron"),
                "has_data": drone_has,
                "timeseries_path": "drone/timeseries.json" if drone_has else None,
                "metadata_path": "drone/metadata.json" if drone_has else None,
                "status": "ready" if drone_has else "pending",
            },
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Listo → {static_dir}  ({len(rasters_meta)} capas WebP)")


if __name__ == "__main__":
    main()
