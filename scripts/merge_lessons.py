#!/usr/bin/env python3
"""Fusiona lessons.md de una run (incremental) con el fichero global."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PATHS


def merge(run_dir: str | None = None) -> str:
    global_lessons = PATHS["memory"] / "lessons.md"
    global_lessons.parent.mkdir(parents=True, exist_ok=True)

    candidates = []
    if run_dir:
        candidates.append(Path(run_dir) / "lessons_incremental.md")
    # todos los incrementales sin mergear
    for inc in sorted(PATHS["runs"].glob("*/lessons_incremental.md")):
        if inc.stat().st_size > 0:
            candidates.append(inc)

    merged = []
    for inc in candidates:
        if not inc.exists():
            continue
        content = inc.read_text()
        if not content.strip():
            continue
        merged.append(f"# desde {inc.parent.name}\n{content}")
        # vaciar para no re-mergear
        inc.write_text("")

    if not merged:
        return "Nada que fusionar."
    text = "\n\n" + "\n\n".join(merged) + "\n"
    with global_lessons.open("a") as f:
        f.write(text)
    return f"Fusionadas {len(merged)} lecciones a {global_lessons}"


if __name__ == "__main__":
    print(merge(sys.argv[1] if len(sys.argv) > 1 else None))