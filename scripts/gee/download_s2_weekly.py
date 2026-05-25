#!/usr/bin/env python3
"""
Exporta imágenes de la ImageCollection semanal S2 (Pumahuida) a Google Drive y las
copia al repositorio local en ``data/sentinel2/``.

Flujo:
  1. Lista hijos en ``projects/ee-teleamb/assets/S2_weekly_pumahuida`` (patrón ``Y*_W*``).
  2. Encola ``Export.image.toDrive`` por cada semana faltante en local.
  3. Espera tareas GEE (opcional).
  4. Descarga desde Drive vía API → ``data/sentinel2/`` (mismo patrón que fic_agro).

Requisitos: ``earthengine authenticate`` (incluye alcance de Drive).

Uso (desde la raíz ``fondecyt_puc/``):

    python scripts/gee/download_s2_weekly.py --dry-run
    python scripts/gee/download_s2_weekly.py
    python scripts/gee/download_s2_weekly.py --sync-only
    python scripts/gee/download_s2_weekly.py --export-only --no-wait
    python scripts/gee/download_s2_weekly.py --force
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import ee
import yaml

if __name__ == "__main__" and not __package__:
    _repo = Path(__file__).resolve().parents[2]
    if str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))
    __package__ = "scripts.gee"

from . import paths
from .drive_sync import run_drive_sync

_WEEKLY_BASENAME_RE = re.compile(r"^Y(\d{4})_W(\d{2})$", re.IGNORECASE)


def _load_config() -> dict:
    cfg_path = paths.CONFIG_PATH
    if not cfg_path.is_file():
        return {}
    with open(cfg_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("gee") or {}


def _resolve_settings(args: argparse.Namespace) -> dict:
    cfg = _load_config()
    collection = (
        args.collection
        or paths.GEE_COLLECTION
        or cfg.get("collection")
        or "projects/ee-teleamb/assets/S2_weekly_pumahuida"
    )
    cloud_project = (
        args.project
        or paths.GEE_CLOUD_PROJECT
        or cfg.get("cloud_project")
        or cfg.get("project")  # compat. nombre antiguo
        or ""
    ).strip()
    drive_folder = (
        args.drive_folder
        or paths.DRIVE_S2_EXPORT_FOLDER
        or cfg.get("drive_folder")
        or "FONDECYT_S2_weekly_pumahuida"
    )
    scale = float(args.scale if args.scale is not None else cfg.get("scale_m", paths.DEFAULT_SCALE_M))
    return {
        "collection": collection.strip().rstrip("/"),
        "cloud_project": cloud_project,
        "drive_folder": drive_folder.strip(),
        "scale": scale,
        "dest_dir": paths.REPO_S2_DIR,
    }


def _init_failure_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "403" in msg
        or "permission" in msg
        or "serviceusage" in msg
        or "no project found" in msg
        or "user_project_denied" in msg
    )


def initialize_ee(cloud_project: str) -> str:
    """
    Inicializa Earth Engine con un proyecto Cloud donde la cuenta tenga permiso.

    El asset puede vivir en ``projects/ee-teleamb/...``; eso es independiente del
    proyecto pasado a ``ee.Initialize()``.
    """
    tried: list[str] = []
    seen: set[str] = set()
    candidates: list[str | None] = []

    def _add(proj: str | None) -> None:
        key = proj or ""
        if key in seen:
            return
        seen.add(key)
        candidates.append(proj)

    if cloud_project:
        _add(cloud_project)
    env_proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if env_proj:
        _add(env_proj)
    for fb in paths.GEE_CLOUD_PROJECT_FALLBACKS:
        _add(fb)
    _add(None)  # último recurso: proyecto en credentials (si existe)

    last_err: BaseException | None = None
    for proj in candidates:
        label = proj or "(por defecto / credenciales EE)"
        tried.append(label)
        try:
            if proj:
                ee.Initialize(project=proj)
            else:
                ee.Initialize()
            print(f"Earth Engine inicializado con proyecto Cloud: {label}")
            if cloud_project and proj and proj != cloud_project:
                print(
                    f"  (Aviso: pediste {cloud_project} pero funcionó {proj}. "
                    "Pide IAM en teleamb-494020 o usa --project explícito.)",
                    file=sys.stderr,
                )
            return label
        except Exception as exc:
            last_err = exc
            if _init_failure_retryable(exc):
                short = str(exc).split("\n")[0]
                print(f"  No usable {label}: {short}", file=sys.stderr)
                continue
            raise

    raise RuntimeError(
        "No se pudo inicializar Earth Engine con ningún proyecto Cloud probado.\n"
        f"  Intentos: {', '.join(tried)}\n\n"
        "  Si quieres usar teleamb-494020, un admin del proyecto debe:\n"
        "    1. Activar Earth Engine API en https://console.cloud.google.com/apis/library/earthengine.googleapis.com?project=teleamb-494020\n"
        "    2. Añadir tu cuenta con rol «Service Usage Consumer» (serviceusage.serviceUsageConsumer)\n"
        "       y acceso a Earth Engine en https://console.cloud.google.com/iam-admin/iam?project=teleamb-494020\n"
        "    3. Registrarte en https://code.earthengine.google.com/ con esa cuenta\n"
        "    4. Re-autenticar: earthengine authenticate --project=teleamb-494020 --force\n\n"
        "  Mientras tanto, prueba un proyecto donde ya tengas permiso:\n"
        "    python scripts/gee/download_s2_weekly.py --project teleambagr\n"
        f"\n  Último error: {last_err}"
    ) from last_err


def _image_for_drive_export(img: ee.Image) -> ee.Image:
    """GeoTIFF en Drive no admite bandas Long; convertir a float64."""
    return ee.Image(img).toDouble()


def list_weekly_basenames(collection_id: str) -> list[str]:
    """Lista nombres ``Y{year}_W{week}`` de imágenes en la ImageCollection."""
    prefix = collection_id.rstrip("/")
    try:
        result = ee.data.listAssets({"parent": prefix})
    except ee.EEException as exc:
        raise RuntimeError(f"No se pudo listar assets en {prefix}: {exc}") from exc

    basenames: set[str] = set()
    for item in result.get("assets", []):
        asset_id = (item.get("id") or "").rstrip("/")
        base = asset_id.split("/")[-1]
        if _WEEKLY_BASENAME_RE.match(base):
            basenames.add(base)

    def _sort_key(b: str) -> tuple[int, int]:
        m = _WEEKLY_BASENAME_RE.match(b)
        assert m is not None
        return int(m.group(1)), int(m.group(2))

    return sorted(basenames, key=_sort_key)


def existing_local_stems(dest_dir: Path) -> set[str]:
    stems: set[str] = set()
    if not dest_dir.is_dir():
        return stems
    for p in dest_dir.iterdir():
        if p.is_file() and p.suffix.lower() in (".tif", ".tiff"):
            stems.add(p.stem)
    return stems


def wait_for_export_tasks(
    tasks: list[ee.batch.Task],
    *,
    poll_seconds: float = 30.0,
) -> None:
    if not tasks:
        return
    n = len(tasks)
    poll_seconds = max(5.0, poll_seconds)
    print(f"\nEsperando {n} tarea(s) GEE → Drive (cada {poll_seconds:g}s)…", flush=True)
    start = time.monotonic()
    while True:
        if not any(t.active() for t in tasks):
            break
        elapsed = int(time.monotonic() - start)
        active = sum(1 for t in tasks if t.active())
        print(f"  {n - active}/{n} completadas; {active} activas ({elapsed}s)…", flush=True)
        time.sleep(poll_seconds)

    failed: list[str] = []
    for t in tasks:
        info = t.status()
        st = info.get("state")
        st_s = st.value if hasattr(st, "value") else str(st)
        if st_s != "COMPLETED":
            failed.append(f"{st_s}: {info.get('error_message', '')}")
    if failed:
        raise RuntimeError("Exportaciones fallidas:\n" + "\n".join(failed[:20]))


def enqueue_exports(
    collection_id: str,
    basenames: list[str],
    *,
    drive_folder: str,
    scale: float,
    dest_dir: Path,
    skip_stems: set[str],
    dry_run: bool,
) -> list[ee.batch.Task]:
    tasks: list[ee.batch.Task] = []
    prefix = collection_id.rstrip("/")

    for base in basenames:
        stem = base
        if stem in skip_stems:
            print(f"  [omitir] {stem}.tif (ya en {dest_dir})")
            continue

        asset_id = f"{prefix}/{base}"
        img = ee.Image(asset_id)
        region = img.geometry().bounds()

        if dry_run:
            print(f"  [dry-run] {stem}.tif → Drive/{drive_folder}")
            continue

        desc = f"Pumahuida_{stem}"[:100]
        task = ee.batch.Export.image.toDrive(
            image=_image_for_drive_export(img),
            description=desc,
            folder=drive_folder,
            fileNamePrefix=stem,
            region=region,
            scale=scale,
            crs="EPSG:4326",
            maxPixels=1e13,
            fileFormat="GeoTIFF",
        )
        task.start()
        tasks.append(task)
        print(f"  Encolado: {stem}.tif → Drive/{drive_folder}")

    return tasks


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="S2 semanal Pumahuida: GEE ImageCollection → Drive → data/sentinel2/"
    )
    parser.add_argument("--dry-run", action="store_true", help="Solo listar; no encolar ni descargar.")
    parser.add_argument("--export-only", action="store_true", help="Solo encolar exports a Drive.")
    parser.add_argument("--sync-only", action="store_true", help="Solo copiar desde Drive al repo.")
    parser.add_argument("--no-wait", action="store_true", help="No esperar COMPLETED de tareas GEE.")
    parser.add_argument("--force", action="store_true", help="Re-encolar aunque el .tif exista en local.")
    parser.add_argument("--full-sync", action="store_true", help="Espejo completo Drive → local.")
    parser.add_argument(
        "--collection",
        default="",
        help=f"ImageCollection GEE (default: {paths.GEE_COLLECTION})",
    )
    parser.add_argument(
        "--project",
        default="",
        metavar="CLOUD_PROJECT",
        help="Proyecto Google Cloud para ee.Initialize() (p. ej. teleamb-494020). "
        "No es el dueño del asset ee-teleamb.",
    )
    parser.add_argument(
        "--drive-folder",
        default="",
        help=f"Carpeta en Drive (default: {paths.DRIVE_S2_EXPORT_FOLDER})",
    )
    parser.add_argument("--scale", type=float, default=None, help="Resolución en metros (default: 10).")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=30.0,
        help="Intervalo al esperar tareas GEE.",
    )
    args = parser.parse_args(argv)

    if args.export_only and args.sync_only:
        print("Use solo uno de --export-only o --sync-only.", file=sys.stderr)
        sys.exit(2)

    settings = _resolve_settings(args)
    dest_dir = settings["dest_dir"]
    dest_dir.mkdir(parents=True, exist_ok=True)

    print("=== Fondecyt PUC — S2 semanal Pumahuida ===")
    cloud_hint = settings["cloud_project"] or "autodetectar"
    print(f"Proyecto Cloud (API): {cloud_hint}")
    print(f"Colección    : {settings['collection']}")
    print(f"Carpeta Drive: {settings['drive_folder']}")
    print(f"Destino local: {dest_dir}")
    print(f"Escala       : {settings['scale']} m")

    tasks: list[ee.batch.Task] = []

    if not args.sync_only:
        initialize_ee(settings["cloud_project"])
        basenames = list_weekly_basenames(settings["collection"])
        print(f"\nImágenes en colección: {len(basenames)}")
        if not basenames:
            print("No hay assets Y*_W* en la colección.", file=sys.stderr)
        else:
            skip = set() if args.force else existing_local_stems(dest_dir)
            print(f"\n=== Exportar a Drive ===")
            if skip and not args.force:
                print(f"Omitiendo {len(skip)} semana(s) ya presentes en local.")
            tasks = enqueue_exports(
                settings["collection"],
                basenames,
                drive_folder=settings["drive_folder"],
                scale=settings["scale"],
                dest_dir=dest_dir,
                skip_stems=skip,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                print(f"Tareas encoladas: {len(tasks)}")

        if tasks and not args.dry_run and not args.no_wait:
            wait_for_export_tasks(tasks, poll_seconds=args.poll_seconds)
        elif tasks and args.no_wait:
            print("\n(--no-wait: continúa sin esperar; ejecute de nuevo más tarde para sincronizar.)")

    if not args.export_only:
        print("\n=== Sincronizar Drive → repo ===")
        if args.dry_run:
            print("[dry-run] se llamaría run_drive_sync(['s2'], dry_run=True)")
        else:
            run_drive_sync(
                ["s2"],
                dry_run=False,
                full_replace=True if args.full_sync else None,
            )

    print("\nListo.")


if __name__ == "__main__":
    main()
