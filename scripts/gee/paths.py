"""Rutas del proyecto y carpeta en Google Drive para exportaciones S2."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

REPO_S2_DIR = PROJECT_ROOT / "data" / "sentinel2"

# Sobrescribir: FONDECYT_DRIVE_S2_FOLDER
DRIVE_S2_EXPORT_FOLDER = (
    os.environ.get("FONDECYT_DRIVE_S2_FOLDER", "").strip()
    or "FONDECYT_S2_weekly_pumahuida"
)

GEE_COLLECTION = (
    os.environ.get("FONDECYT_GEE_COLLECTION", "").strip()
    or "projects/ee-teleamb/assets/S2_weekly_pumahuida"
)

# Proyecto Cloud para ee.Initialize() (no confundir con el dueño del asset ee-teleamb).
GEE_CLOUD_PROJECT = os.environ.get("FONDECYT_GEE_CLOUD_PROJECT", "").strip() or os.environ.get(
    "FONDECYT_GEE_PROJECT", ""
).strip()
GEE_CLOUD_PROJECT_FALLBACKS = ("teleamb-494020", "teleambagr", "ee-javiermedinam")

DEFAULT_SCALE_M = 10.0
