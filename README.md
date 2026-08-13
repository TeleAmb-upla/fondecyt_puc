# Fondecyt PUC — sitio estático (Pumahuida)

Explorador web de índices satelitales semanales (Sentinel-2 óptico y Sentinel-1 SAR) y de vuelos de dron para tres predios en Pumahuida (PUC · Teleamb).

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
    ├── sentinel2/          # óptico: NDVI, NDWI, NDCI, LAI…
    │   ├── metadata.json
    │   ├── timeseries.json
    │   └── rasters/*.webp
    ├── sentinel1/          # SAR: RVI, γ0 VV/VH, humedad relativa (cambio VV)
    │   ├── metadata.json
    │   ├── timeseries.json
    │   └── rasters/*.webp
    └── drone/
        ├── metadata.json
        ├── timeseries.json
        ├── pointclouds/*.json
        └── rasters/*.webp
```

Ambas fuentes satelitales comparten la misma definición de semana ISO (lunes–domingo,
asignada al año civil que contiene su jueves), de modo que sus series son comparables.
