# Fondecyt PUC — sitio estático (Pumahuida)

Explorador web de índices Sentinel-2 semanales para tres predios en Pumahuida (PUC · Teleamb).

Este repositorio en GitHub contiene **solo el frontend**: HTML, assets, `data_static/` (JSON, GeoJSON y capas `.webp`).

El pipeline de descarga GEE y generación de WebP se ejecuta en local (`scripts/`, `data/`); no se versionan aquí.

## Ver en local

```bash
cd fondecyt_puc
python -m http.server 8090
```

Abre http://localhost:8090/explorador.html

## Estructura publicada

```text
fondecyt_puc/
├── index.html
├── explorador.html
├── assets/img/
└── data_static/
    ├── sources_manifest.json
    ├── predios_aoi.geojson
    └── sentinel2/
        ├── metadata.json
        ├── timeseries.json
        └── rasters/*.webp
```
