"""Crítico VLM de CREATIVIDAD (eje anti-proxy).

El eje 'visual' del evaluador es un proxy ESTÁTICO (cuenta @keyframes, canvas,
gradientes... en el código) que el agente aprende a rellenar sin que el resultado
sea mejor. La categoría 'creativity' evalúa lo VISIBLE en el screenshot con un
VLM, con criterios de diseño de vanguardia: composición no estándar, tipografía
expresiva, grid roto con propósito, micro-interacciones, cohesión y originalidad.

Al ser una señal sobre el resultado renderizado (no sobre el código), no es
sobreajustable con strings: el agente tiene que hacer algo realmente distinto.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import PATHS
from tools.base import Tool
from tools.domain.visual_critic import find_chrome, render_screenshot

CREATIVE_PROMPT = """Eres un crítico de diseño de vanguardia (VLM). Mira el screenshot de la página renderizada y evalúa la CREATIVIDAD REAL del diseño visual, NO el código ni los checks técnicos.

Puntúa del 0 al 100 según qué tan lejos llega el diseño frente a una plantilla genérica:
- Originalidad de la composición: grid roto intencional, asimetría con propósito, layout inesperado
- Tipografía expresiva: uso de fuentes display/serif de carácter, jerarquía tipográfica dramática
- Movimiento y micro-interacciones: animaciones con intención, hover con respuesta, scroll-reveal bien puesto
- Cohesión artística: paleta distintiva, acento de color con carácter, textura/gradientes con criterio
- Nivel de acabado: sin plantillas obvias, sin look genérico, se siente diseñado por una persona

Puntúa BAJO (0-30) si parece una plantilla Bootstrap/template genérica.
Puntúa MEDIO (30-60) si está bien hecho pero convencional.
Puntúa ALTO (60-85) si tiene ideas visuales distintivas bien ejecutadas.
Puntúa MUY ALTO (85-100) si es diseño de portafolio de agencia top.

Devuelve EXCLUSIVAMENTE JSON válido (sin markdown, sin texto extra):
{
  "score": 0-100,
  "issues": ["aspecto concreto visible en el screenshot que baja la creatividad"],
  "suggestions": ["idea visual específica y accionable para el siguiente generate_candidate"]
}
Reglas:
- Máximo 4 issues y 4 suggestions. Concretos y visibles en el screenshot.
- Si el screenshot no permite distinguir algo, no lo inventes.
- Sé exigente: el diseño genérico es la norma, la creatividad es la excepción.
"""


class AuditCreative(Tool):
    name = "audit_creative"
    description = (
        "Crítica VLM de CREATIVIDAD del candidato actual: renderiza workspace/current "
        "a screenshot y devuelve score creativity 0-100, issues y sugerencias de diseño "
        "de vanguardia. A diferencia de audit_visual (corrección estética), esta puntúa "
        "lo NOVEDOSO del resultado visible: composición no estándar, tipografía "
        "expresiva, micro-interacciones, cohesión artística. Úsala para que el agente "
        "haga algo DISTINTO, no solo 'correcto'."
    )

    def __init__(self, llm=None):
        self.llm = llm
        super().__init__()

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "Aspecto creativo concreto a criticar (opcional)",
                    },
                },
            },
        }

    def run(self, focus: str = "", **kwargs) -> str:
        target = PATHS["current"]
        if not (target / "index.html").exists():
            return f"ERROR: no existe index.html en {target}"

        png = PATHS["current"] / ".creative.png"
        ok = render_screenshot(target / "index.html", png)
        if not ok:
            return "ERROR: no se pudo renderizar screenshot (Chrome headless no disponible)."

        prompt = CREATIVE_PROMPT
        if focus:
            prompt += f"\n\nEnfócate especialmente en: {focus}."

        try:
            resp = self.llm.generate_vision(prompt, png.read_bytes(), "image/png")
            raw = resp.text
        except Exception as e:
            return f"ERROR: crítica VLM de creatividad falló: {e}"
        finally:
            png.unlink(missing_ok=True)

        score, issues, suggestions = self._parse(raw)
        lines = [f"creativity_vlm={score}"]
        lines += [f"Issues ({len(issues)}):"]
        lines += [f"- {i}" for i in issues] or ["- (sin issues)"]
        lines.append(f"Sugerencias ({len(suggestions)}):")
        lines += [f"- {s}" for s in suggestions] or ["- (sin sugerencias)"]
        return "\n".join(lines)

    @staticmethod
    def _parse(raw: str) -> tuple[int, list[str], list[str]]:
        if not raw:
            return 0, [], []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                return 0, [], []
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return 0, [], []
        if not isinstance(data, dict):
            return 0, [], []
        score = int(data.get("score", 0)) if isinstance(data.get("score"), (int, float)) else 0
        score = max(0, min(100, score))
        issues = [str(i).strip() for i in (data.get("issues") or []) if str(i).strip()]
        suggestions = [str(s).strip() for s in (data.get("suggestions") or []) if str(s).strip()]
        return score, issues[:4], suggestions[:4]