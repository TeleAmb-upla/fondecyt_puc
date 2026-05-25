# Fondecyt PUC — Pumahuida (Sentinel-2 semanal)

Proyecto conjunto **PUC** y **Teleamb**: tres parcelas en Pumahuida, índices Sentinel-2 semanales y explorador web (sin histórico interanual).

## Estructura

```text
fondecyt_puc/
├── config.yaml
├── explorador.html          # mapa + gráfico semanal (3 parcelas)
├── index.html
├── assets/img/puc_escudo.svg
├── data/
│   ├── sentinel2/           # Y2025_W10.tif, …
│   └── vectors/pumahuida/   # pumahuida_exotico.shp, cae1, cae2
├── data_static/             # salida para el navegador
│   ├── sources_manifest.json
│   ├── wetlands_aoi.geojson
│   └── sentinel2/
│       ├── metadata.json
│       ├── timeseries.json
│       └── rasters/*.webp
└── scripts/
    ├── gee/download_s2_weekly.py
    └── static_site/build_sentinel2_local.py
```

## Flujo de datos

1. **Descarga GEE → Drive → local**  
   `python scripts/gee/download_s2_weekly.py`

2. **Extracción por parcela + WebP**  
   `python scripts/static_site/build_sentinel2_local.py`  
   Calcula la **media semanal** de cada índice dentro de cada polígono y genera capas para el mapa.

3. **Visualización**  
   ```bash
   python -m http.server 8090
   ```
   Abre http://localhost:8090/explorador.html

## Explorador

- **Parcelas:** Exótico, CAE 1, CAE 2 (selector para el mapa; el gráfico muestra las tres a la vez).
- **Índices:** todas las bandas del GeoTIFF (NDVI, NDMI, NDWI, EVI, LAI, …).
- **Mapa:** semana seleccionada + índice + parcela activa.
- **Gráfico:** seguimiento semanal con **una línea por parcela** (colores y leyenda); clic en un punto cambia la semana del mapa.

## Requisitos

```bash
pip install -r requirements.txt
earthengine authenticate --project=teleamb-494020
```

Cuenta recomendada: **teleamb@upla.cl**. Si OAuth falla, ver sección de autenticación en commits anteriores o usar `earthengine authenticate --auth_mode=gcloud`.

## Parcelas

Shapefiles en `data/vectors/pumahuida/`:

- `pumahuida_exotico.shp`
- `pumahuida_cae1.shp`
- `pumahuida_cae2.shp`

Tras cambiar geometrías, vuelve a ejecutar `build_sentinel2_local.py`.
