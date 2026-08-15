"""Snapshot del harness: hash de los directorios que definen el comportamiento
del agente (domain/, tools/, .agent/prompts/) para poder medir la evolución del
harness entre runs.

Un "snapshot" es un dict:
    {
      "tree_hash": sha256 de la concatenación ordenada de (ruta, contenido),
      "n_files": número de archivos hasheados,
      "files": {ruta_relativa: sha256_por_archivo},
    }

Permite:
  - conocer la versión del harness en una run (tree_hash),
  - ver QUÉ archivos cambiaron entre dos runs (diff_snapshots).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from config import PATHS

HARNESS_DIRS = ("domain", "tools", ".agent/prompts")


def _iter_harness_files() -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for name in HARNESS_DIRS:
        base = PATHS["root"] / name
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(PATHS["root"]))
                try:
                    out.append((rel, p.read_bytes()))
                except OSError:
                    continue
    return out


def snapshot() -> dict:
    """Calcula el hash de la versión actual del harness."""
    files = sorted(_iter_harness_files())
    h = hashlib.sha256()
    file_hashes: dict[str, str] = {}
    for rel, data in files:
        fh = hashlib.sha256(data).hexdigest()[:16]
        file_hashes[rel] = fh
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(fh.encode("utf-8"))
        h.update(b"\0")
    return {
        "tree_hash": h.hexdigest(),
        "n_files": len(files),
        "files": file_hashes,
    }


def task_hash(task: str) -> str:
    """Hash estable de la tarea (para agrupar runs de un mismo benchmark)."""
    import re

    norm = re.sub(r"\s+", " ", (task or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def diff_snapshots(a: dict | None, b: dict | None) -> list[str]:
    """Lista de cambios legibles entre dos snapshots (None => snapshot desconocido)."""
    a_files = (a or {}).get("files", {})
    b_files = (b or {}).get("files", {})
    lines: list[str] = []
    for rel in sorted(set(a_files) | set(b_files)):
        ha, hb = a_files.get(rel), b_files.get(rel)
        if ha is None:
            lines.append(f"  + añadido {rel}")
        elif hb is None:
            lines.append(f"  - eliminado {rel}")
        elif ha != hb:
            lines.append(f"  ~ modificado {rel}")
    return lines