# Ortofotos dron

Coloca GeoTIFF por parcela y fecha, por ejemplo:

```text
data/drone/exotico_20250415_ndvi.tif
data/drone/exotico_20250415_ndwi.tif
data/drone/exotico_20250415_rgb.tif
```

Luego ejecuta (cuando exista el exportador):

```bash
python scripts/static_site/export_drone.py
```

Hasta entonces el explorador muestra el origen **Dron** deshabilitado con aviso.
