"""Crítico VLM (capa estética de AutoDesign, §3.4): evalúa el candidato actual de
workspace/current renderizado como screenshot y devuelve un score estético 0-100
con issues y sugerencias concretas. Es el feedback que guía la siguiente mutación
de generate_candidate para que las mejoras visuales se acumulen."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import PATHS
from tools.base import Tool

CRITIC_PROMPT = """Eres un crítico de diseño web senior (VLM). Mira el screenshot de la página renderizada.

Evalúa la CALIDAD ESTÉTICA y de UX VISUAL, no el código. Es una landing de
grafo de conocimientos personal (SVG interactivo de repositorios de IA).

Puntúa del 0 al 100 según:
- Jerarquía visual y equilibrio (todo centrado/alineado, sin solapamientos ni descentramiento)
- Legibilidad (contraste, tamaño tipográfico, texto dentro de los círculos)
- Interactividad visible (hover, nodos expandibles, feedback al usuario)
- Coherencia estética (paleta, dark/light, espaciados, sombras, gradientes)
- Ausencia de espacios vacíos o elementos cortados

Devuelve EXCLUSIVAMENTE JSON válido (sin markdown, sin texto extra):
{
  "score": 0-100,
  "issues": ["issue concreto observable en el screenshot"],
  "suggestions": ["sugerencia accionable y específica para el siguiente generate_candidate"]
}
Reglas:
- Máximo 4 issues y 4 suggestions. Sé concreto y específico (ej. "los subnodos quedan descentrados a la derecha").
- Si algo no se distingue bien en el screenshot, no lo inventes: solo reporta lo visible.
- Sé exigente: por debajo de 90 hay margen de mejora.
"""


def find_chrome() -> str | None:
    for p in (
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    ):
        if Path(p).exists():
            return p
    return None


def render_screenshot(html_path: Path, png_path: Path, viewport: str = "1280,900") -> bool:
    """Renderiza un index.html a PNG con Chrome/Edge headless de Windows (WSL)."""
    chrome = find_chrome()
    if not chrome:
        return False
    try:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        html_path = html_path.resolve()
        png_path = png_path.resolve()
        try:
            if Path("/usr/bin/wslpath").exists():
                _win = lambda p: subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True).stdout.strip()
            else:
                raise OSError
        except OSError:
            _win = lambda p: str(p).replace("/mnt/c/", "C:\\").replace("/", "\\")
        url = "file://" + _win(html_path)
        shot = _win(png_path)
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={viewport}",
            "--screenshot=" + shot,
            url,
        ]
        subprocess.run(cmd, capture_output=True, timeout=90)
        return png_path.exists() and png_path.stat().st_size > 0
    except Exception:
        return False


class AuditVisual(Tool):
    name = "audit_visual"
    description = (
        "Crítica estética del candidato actual con un VLM: renderiza workspace/current "
        "a screenshot (Chrome headless) y devuelve score visual 0-100, issues visibles "
        "y sugerencias concretas. Úsala tras generate_candidate para detectar fallos "
        "de diseño (descentramiento, solapamientos, legibilidad) y guiar la siguiente "
        "mutación estética."
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
                        "description": "Aspecto concreto a criticar (opcional, p. ej. 'centrado del grafo')",
                    },
                },
            },
        }

    def run(self, focus: str = "", **kwargs) -> str:
        from .evaluator import evaluate

        target = PATHS["current"]
        if not (target / "index.html").exists():
            return f"ERROR: no existe index.html en {target}"

        metrics = evaluate(target)
        baseline = metrics.get("visual")
        png = PATHS["current"] / ".audit.png"
        ok = render_screenshot(target / "index.html", png)
        if not ok:
            return (
                f"ERROR: no se pudo renderizar screenshot (Chrome headless no disponible). "
                f"visual estático={baseline} (sin crítica VLM)."
            )

        prompt = CRITIC_PROMPT
        if focus:
            prompt += f"\n\nEnfócate especialmente en: {focus}."

        try:
            resp = self.llm.generate_vision(prompt, png.read_bytes(), "image/png")
            raw = resp.text
        except Exception as e:
            return f"ERROR: crítica VLM falló: {e} (visual estático={baseline})"
        finally:
            png.unlink(missing_ok=True)

        score, issues, suggestions = self._parse(raw)
        lines = [
            f"visual_vlm={score} | visual_estatico={baseline}",
            f"Issues ({len(issues)}):",
        ]
        lines += [f"- {i}" for i in issues] or ["- (sin issues)"]
        lines.append(f"Sugerencias ({len(suggestions)}):")
        lines += [f"- {s}" for s in suggestions] or ["- (sin sugerencias)"]
        from .evaluator import metrics_block
        lines.append(metrics_block({"visual_vlm": score, "visual_estatico": baseline}))
        return "\n".join(lines)

    @staticmethod
    def _parse(raw: str) -> tuple[int, list[str], list[str]]:
        """Extrae score/issues/suggestions del JSON del VLM (tolerante a ruido)."""
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