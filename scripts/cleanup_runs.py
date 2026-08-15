#!/usr/bin/env python3
"""Limpieza manual de runs/ (default --dry-run, requiere --yes para aplicar).

Operaciones:
  --keep N              Borra las runs más antiguas conservando las N más recientes
                        (solo si ya están backfilleadas en memory/memory.db).
  --archive DIR         Mueve las runs candidatas a borrar a DIR/runs_backup_<ts>.tar.gz
                        en vez de borrarlas.
  --prune-dashboards    Elimina los dashboard_*.html sueltos en la raíz de runs/
                        (artefactos viejos, regenerables con render_dashboard --run).
  --prune-orphans       Elimina runs/lessons_incremental.md raíz (huérfano ya backfilleado).

Uso:
    python -m scripts.cleanup_runs --keep 6 --prune-dashboards --dry-run
    python -m scripts.cleanup_runs --keep 6 --prune-dashboards --yes
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from config import PATHS

RUN_PATTERN = re.compile(r"^\d{8}T\d{6}--.+")


def run_dirs() -> list[Path]:
    return sorted(
        (p for p in PATHS["runs"].iterdir()
         if p.is_dir() and RUN_PATTERN.match(p.name)),
        key=lambda p: p.name,
    )


def _backfilled(db: MemoryDB, run_id: str) -> bool:
    r = db.get_run(run_id)
    return bool(r and r.get("status") == "done")


def select_oldest(runs: list[Path], keep: int) -> list[Path]:
    return runs[:-keep] if keep > 0 and len(runs) > keep else []


def archive_paths(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / f"runs_backup_{datetime.now().strftime('%Y%m%dT%H%M%S')}.tar.gz"


def main() -> None:
    ap = argparse.ArgumentParser(description="Limpieza manual de runs/")
    ap.add_argument("--keep", type=int, default=None, help="Conservar N runs más recientes")
    ap.add_argument("--archive", type=Path, default=None,
                    help="Empacar runs a borrar en este directorio (tar.gz) en vez de borrar")
    ap.add_argument("--prune-dashboards", action="store_true",
                    help="Eliminar dashboard_*.html sueltos en la raíz de runs/")
    ap.add_argument("--prune-orphans", action="store_true",
                    help="Eliminar runs/lessons_incremental.md raíz (huérfano)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Solo mostrar qué se haría (default si no se da --yes)")
    ap.add_argument("--yes", action="store_true", help="Confirmar y aplicar")
    args = ap.parse_args()

    if not args.yes:
        args.dry_run = True

    db = MemoryDB()
    planned: list[str] = []
    to_delete: list[Path] = []

    # 1) runs antiguas
    if args.keep is not None:
        runs = run_dirs()
        oldest = select_oldest(runs, args.keep)
        if oldest:
            for rd in oldest:
                run_id = rd.name
                if _backfilled(db, run_id):
                    to_delete.append(rd)
                    planned.append(f"Borrar run {run_id} (backfilleada, -{args.keep} conserva "
                                   f"{len(runs) - len(oldest)}/{len(runs)})")
                else:
                    planned.append(f"SKIP run {run_id}: NO está en la DB (corre backfill_memory primero)")
        else:
            planned.append(f"No hay runs que borrar con --keep {args.keep} "
                           f"({len(runs)} runs en total)")

    # 2) dashboards sueltos
    loose_dashboards = []
    if args.prune_dashboards:
        loose_dashboards = sorted(
            p for p in PATHS["runs"].glob("dashboard_*.html") if p.is_file()
        )
        for p in loose_dashboards:
            planned.append(f"Borrar dashboard suelto {p.name}")

    # 3) huérfano lessons_incremental.md raíz
    orphan = PATHS["runs"] / "lessons_incremental.md"
    if args.prune_orphans and orphan.exists():
        planned.append(f"Borrar huérfano {orphan.name}")

    # --- aplicar ---
    if not planned:
        print("Nada que hacer.")
        return

    print("\n".join(planned))
    print(f"\n{len(planned)} acción(es) planificada(s) | dry_run={args.dry_run}")

    if args.dry_run:
        db.close()
        return

    if args.archive is not None and to_delete:
        tarball = archive_paths(args.archive)
        with tarfile.open(tarball, "w:gz") as tf:
            for rd in to_delete:
                tf.add(rd, arcname=rd.name)
        print(f"Empacadas {len(to_delete)} runs en {tarball}")

    for rd in to_delete:
        shutil.rmtree(rd)
        print(f"  borrada {rd.name}")

    for p in loose_dashboards:
        p.unlink()
        print(f"  borrado {p.name}")

    if args.prune_orphans and orphan.exists():
        orphan.unlink()
        print(f"  borrado {orphan.name}")

    db.close()


if __name__ == "__main__":
    main()