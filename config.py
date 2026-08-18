import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT / ".env")

# --- Configuración base ---
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

PATHS = {
    "root": ROOT,
    "agent": ROOT / ".agent",
    "prompts": ROOT / ".agent" / "prompts",
    "tools": ROOT / "tools",
    "domain": ROOT / "domain",
    "memory": ROOT / "memory",
    "runs": ROOT / "runs",
    "workspace": ROOT / "workspace",
    "current": ROOT / "workspace" / "current",
    "config": ROOT / "config",
    "scripts": ROOT / "scripts",
    "templates": ROOT / "templates",
    "tests": ROOT / "test",
}

BUDGET_DEFAULTS = {
    "max_turns": 20,
    "max_cost_usd": 5.0,
    "max_wall_time_minutes": 120,
    "stagnation_advisory": 3,
    "stagnation_hard_stop": 12,
    "min_improvement_percent": 2.0,
}

CONTEXT_DEFAULTS = {
    "compaction_threshold_tokens": 60000,
    "max_history_turns": 8,
    "lessons_max_items": 12,
    "search_tree_max_nodes": 15,
}

# Auto-lecciones: cuando una tool de optimización produce un delta (mejora o
# regresión del mejor score) mayor o igual a este umbral, el harness registra
# una lección worked/didnt automáticamente en la run (deduplicada por contenido).
# Es el refuerzo que no depende de que el LLM se acuerde de llamar a update_lessons.
LESSON_AUTO = {
    "delta_threshold": 4.0,   # |delta| >= umbral -> auto-lección
    "max_per_run": 8,         # tope de auto-lecciones por run para no saturar
}

# Componentes funcionales del harness (mapeo AutoDesign, §2.1). Cada meta-edición
# debe apuntar a UN componente para mantener el crédito atribuible de las ganancias.
# Solo los componentes con prefijos en domain/ son editables por el agente; el resto
# (runtime, orchestration, eval_feedback) son código del harness y no se editan aquí.
HARNESS_COMPONENTS = {
    "context_memory": ("generated",),       # skills, workflows, reglas globales
    "tools_specs": ("archetypes",),         # arquetipos: reglas, stack, workflows
}

# Umbral de ceiling para candidatos que incumplen un gate bloqueante (Eq. 8 del
# paper: un P0 gate capa la puntuación). Si un candidato no cumple las secciones
# obligatorias de la tarea, su total no puede superar este techo.
BLOCKING_CEILING = 40

# Caché semántica de LLM (Punto 2, Qwen 3.8): reutiliza respuestas de llamadas
# repetidas (mismas tareas/estados re-ejecutados) cuando el embedding del prompt
# supera LLM_CACHE_THRESHOLD. Desactivable con LLM_CACHE_ENABLED=0 o --no-cache.
LLM_CACHE_ENABLED = os.environ.get("LLM_CACHE_ENABLED", "1") != "0"
LLM_CACHE_THRESHOLD = float(os.environ.get("LLM_CACHE_THRESHOLD", "0.80"))
LLM_CACHE_TTL_DAYS = int(os.environ.get("LLM_CACHE_TTL_DAYS", "7"))

# Sandbox de ejecución de código (Punto 8): "restricted" aplica allowlist de
# módulos Python + prlimit/ulimit en bash; "off" deshabilita la ejecución.
CODE_EXEC_MODE = os.environ.get("CODE_EXEC_MODE", "restricted")

# Gobernanza de skills (Punto 9 — "Practice Makes Unsafe", skill misevolution):
# audita las lecciones antes de escribirlas (write gate), filtra por riesgo en
# la recuperación (retrieval gate) y retira las lecciones con reuses dañinos
# repetidos (SAFEEVOLVE retirement). Simulacro: el crítico es no-bloqueante si
# SKILL_SAFETY_ENABLED=0.
SKILL_SAFETY_ENABLED = os.environ.get("SKILL_SAFETY_ENABLED", "1") != "0"
SKILL_SAFETY_MIN_CU = int(os.environ.get("SKILL_SAFETY_MIN_CU", "3"))  # cu>=3 => reparar
SKILL_SAFETY_RETIRE_AT = int(os.environ.get("SKILL_SAFETY_RETIRE_AT", "2"))  # reuses dañinos

# Precios por 1M tokens (USD) para estimar el coste real de cada llamada.
# clave "default" como fallback si el modelo no está listado.
MODEL_PRICES = {
    "gemini-3.1-pro-preview": (2.50, 15.00),
    "gemini-3.1-pro-preview-customtools": (2.50, 15.00),
    "gemini-3-flash-preview": (0.15, 0.60),
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "default": (1.25, 5.00),
}


def ensure_dirs() -> None:
    for p in PATHS.values():
        p.mkdir(parents=True, exist_ok=True)