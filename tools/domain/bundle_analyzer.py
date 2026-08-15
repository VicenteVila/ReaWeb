"""Análisis del bundle/proyecto: pesos por archivo, detección de dependencias
no usadas (heurística), tamaños de assets."""
from __future__ import annotations

from pathlib import Path

from config import PATHS
from tools.base import Tool


class AnalyzeProject(Tool):
    name = "analyze_project"
    description = (
        "Analiza el proyecto actual (workspace/current): tamaños por tipo de archivo, "
        "archivos más pesados y observaciones de rendimiento."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": {}},
        }

    def run(self, **kwargs) -> str:
        base = PATHS["current"]
        if not base.exists():
            return f"ERROR: {base} no existe"
        files = sorted(base.rglob("*"))
        files = [f for f in files if f.is_file()]
        if not files:
            return "No hay archivos en el proyecto."

        by_type: dict[str, int] = {}
        heavy: list[tuple[int, str]] = []
        for f in files:
            size = f.stat().st_size
            ext = f.suffix if f.suffix else "(sin ext)"
            by_type[ext] = by_type.get(ext, 0) + size
            heavy.append((size, str(f.relative_to(base))))

        heavy.sort(reverse=True)
        total = sum(s for s, _ in heavy)
        type_lines = [f"{k}: {v/1024:.1f} KB" for k, v in sorted(by_type.items(), key=lambda x: -x[1])]
        heavy_lines = [f"{f}: {s/1024:.1f} KB" for s, f in heavy[:5]]

        notes = []
        img = by_type.get(".jpg", 0) + by_type.get(".png", 0) + by_type.get(".gif", 0)
        if img:
            notes.append("Hay imágenes rasterizadas (jpg/png/gif). Considerar WebP/AVIF para performance.")
        if by_type.get(".html", 0) > by_type.get(".css", 0) * 3 and by_type.get(".html", 0) > 50_000:
            notes.append("HTML grande; revisar código inline.")
        if by_type.get(".js", 0) > 300_000:
            notes.append("JS pesado (>300KB); considerar splitting.") 

        return (
            f"Total: {total/1024:.1f} KB en {len(files)} archivos\n"
            f"Por tipo:\n" + "\n".join(type_lines) + "\n"
            f"Archivos más pesados:\n" + "\n".join(heavy_lines) + "\n"
            + ("Observaciones:\n" + "\n".join(notes) if notes else "Sin observaciones críticas.")
        )