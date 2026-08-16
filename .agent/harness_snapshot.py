"""Snapshot del harness: hash de los directorios que definen el comportamiento
del agente (domain/, tools/, .agent/prompts/) para poder medir la evolución del
harness entre runs. También incluye la fuente semilla Docs/ y las lecciones de
la DB (memoria persistente), de modo que cualquier cambio de conocimiento quede
versionado en el snapshot.

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

# Directorios que definen el comportamiento del agente y la fuente semilla.
# Docs/ es la especificación inicial de arquetipos (ver README); domain/ es el
# conocimiento vivo que el agente mejora. Ambos quedan versionados en el hash.
HARNESS_DIRS = ("domain", "tools", ".agent/prompts", "Docs")


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


def lessons_hash() -> str:
    """Hash estable del contenido de lecciones de la DB (memoria persistente).

    Devuelve '' si no hay lecciones o no se puede leer la DB.
    """
    try:
        from agent.memory_db import MemoryDB

        db = MemoryDB()
        try:
            rows = db.conn.execute(
                "SELECT run_id, ts, category, content FROM lessons "
                "ORDER BY run_id, ts, category"
            ).fetchall()
        finally:
            db.close()
    except Exception:
        return ""
    if not rows:
        return ""
    payload = "\n".join(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}" for r in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def snapshot() -> dict:
    """Calcula el hash de la versión actual del harness (incluye Docs/ y memoria)."""
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
    # La memoria (lecciones) es parte viva del conocimiento del agente.
    lh = lessons_hash()
    if lh:
        file_hashes["memory/lessons.db"] = lh
        h.update(b"memory/lessons.db\0")
        h.update(lh.encode("utf-8"))
        h.update(b"\0")
    return {
        "tree_hash": h.hexdigest(),
        "n_files": len(files) + (1 if lh else 0),
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