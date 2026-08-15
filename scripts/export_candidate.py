#!/usr/bin/env python3
"""Exporta el candidato final de una run a un directorio destino."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PATHS


def export(run_id: str, run_dir: str | None = None, dest: str | None = None) -> str:
    base = PATHS["runs"] / run_id if run_dir is None else Path(run_dir)
    finals = list((base / "final").iterdir()) if (base / "final").exists() else []
    if not finals:
        # fallback: último candidato
        cands = sorted((base / "candidates").iterdir()) if (base / "candidates").exists() else []
        if not cands:
            return "No hay candidatos finales en la run."
        src = cands[-1]
    else:
        src = finals[0]

    if dest is None:
        dest = str(Path.cwd() / f"{run_id}_final")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return f"Exportado {src} → {dest}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m scripts.export_candidate <run_id> [dest]")
        sys.exit(1)
    print(export(sys.argv[1], dest=sys.argv[2] if len(sys.argv) > 2 else None))