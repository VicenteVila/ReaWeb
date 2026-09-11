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
    "skills": ROOT / "domain" / "skills",
    "memory": ROOT / "memory",
    "runs": ROOT / "runs",
    "workspace": ROOT / "workspace",
    "current": ROOT / "workspace" / "current",
    "wiki": ROOT / "memory" / "wiki",
    "config": ROOT / "config",
    "scripts": ROOT / "scripts",
    "templates": ROOT / "templates",
    "tests": ROOT / "test",
}

BUDGET_DEFAULTS = {
    "max_turns": 24,
    "max_cost_usd": 5.0,
    "max_wall_time_minutes": 120,
    "stagnation_advisory": 4,
    "stagnation_hard_stop": 16,
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
    "skills": ("skills",),                  # Skill Layer WikiSkill (domain/skills/)
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

# WikiSkill (Google 2026): Wiki Layer global que compone (nunca se revierte) y
# alimenta el Skill Proposer post-run. Desactivable con WIKI_ENABLED=0 o --no-wiki.
WIKI_ENABLED = os.environ.get("WIKI_ENABLED", "1") != "0"

# WikiSkill Fase 3 — bucle evolutivo iterativo (Algorithm 1): número de
# iteraciones del orquestador wiki_evolve.py y tope de turnos ReAct del Skill
# Proposer (léctura de wiki/patrones/traces antes de proponer).
WIKI_EVOLVE_ITERATIONS = int(os.environ.get("WIKI_EVOLVE_ITERATIONS", "3"))
WIKI_PROPOSER_MAX_TURNS = int(os.environ.get("WIKI_PROPOSER_MAX_TURNS", "4"))

# Procedural Graph (Lu et al., 2026): grafo procedural declarativo que organiza
# el conocimiento de "qué hacer ahora" en transiciones tipadas (condition,
# guidance, pitfalls). Localización del nodo activo + subgrafo h-hop + guidance
# situacional en cada turno. Evoluciona vía el PG Proposer post-run
# (component=pg_graph) con acceptance gate. Desactivable con PG_GRAPH_ENABLED=0.
PG_GRAPH_ENABLED = os.environ.get("PG_GRAPH_ENABLED", "1") != "0"
PG_GRAPH_HOPS = int(os.environ.get("PG_GRAPH_HOPS", "2"))   # profundidad del subgrafo
PG_PROPOSER_MAX_TURNS = int(os.environ.get("PG_PROPOSER_MAX_TURNS", "8"))
PG_EVOLVE_ITERATIONS = int(os.environ.get("PG_EVOLVE_ITERATIONS", "3"))

# Re-ranking semántico de skills (patrón LPRA de PEARL, Yang et al., 2026):
# un LLM rankea los skills activos por relevancia al objetivo de la run antes
# de inyectarlos, reteniendo solo el top-K (reduce ruido y tokens).
PG_RERANK_ENABLED = os.environ.get("PG_RERANK_ENABLED", "1") != "0"
PG_RERANK_TOP_K = int(os.environ.get("PG_RERANK_TOP_K", "3"))
PG_RERANK_MIN_SCORE = float(os.environ.get("PG_RERANK_MIN_SCORE", "0.30"))

# SCL (PEARL): distinción core vs. contextuales para la estabilidad de skills.
# Core = skills con >= PG_CORE_CONVERGENT_COUNT ocurrencias convergentes (se
# tratan como núcleo estable); contextuales = el resto (en prueba, pueden fallar).
PG_CORE_CONVERGENT_COUNT = int(os.environ.get("PG_CORE_CONVERGENT_COUNT", "3"))

# Harness estricto: evita auto-cierre prematuro tras H0 cuando hay subtareas en
# FAIL (gate estricto implementado en agente). MIN_HYPOTHESES = mínimo de
# candidatos generados antes de poder auto-cerrarse sin checklist 100% ok.
MIN_HYPOTHESES = int(os.environ.get("MIN_HYPOTHESES", "3"))

# Escalera de temperatura del generador (B): 0.7 por defecto (fase reparación);
# GENERATOR_CREATIVE_TEMP cuando el mejor candidato tiene el checklist 100% ok
# (fase creativa, post-completitud).
GENERATOR_CREATIVE_TEMP = float(os.environ.get("GENERATOR_CREATIVE_TEMP", "0.85"))

# Ante-stall (harness estricto): si el agente emite N turnos seguidos de texto
# meta/JSON inválido sin tool_calls (p.ej. repite create_patterns), el harness
# toma el control y ejecuta una mutación útil (reparar subtareas o refinar).
AUTO_UNBLOCK_AT_STALL = int(os.environ.get("AUTO_UNBLOCK_AT_STALL", "2"))

# Gobernanza de skills (Punto 9 — "Practice Makes Unsafe", skill misevolution):
# audita las lecciones antes de escribirlas (write gate), filtra por riesgo en
# la recuperación (retrieval gate) y retira las lecciones con reuses dañinos
# repetidos (SAFEEVOLVE retirement). Simulacro: el crítico es no-bloqueante si
# SKILL_SAFETY_ENABLED=0.
SKILL_SAFETY_ENABLED = os.environ.get("SKILL_SAFETY_ENABLED", "1") != "0"
SKILL_SAFETY_MIN_CU = int(os.environ.get("SKILL_SAFETY_MIN_CU", "3"))  # cu>=3 => reparar
SKILL_SAFETY_RETIRE_AT = int(os.environ.get("SKILL_SAFETY_RETIRE_AT", "2"))  # reuses dañinos

# Selección adaptativa de tareas de validación (Punto 10 — "Task-CoEvolve",
# Miyai et al., arXiv:2608.20169): la suite/gate no evalúa el pool completo en
# cada pasada sino un subconjunto muestreado con pesos proporcionales a la
# varianza histórica del score (tareas donde los candidatos discrepan), y estima
# el score full-suite corrigiendo por la probabilidad de inclusión π_t.
TASK_COEVOLVE_ENABLED = os.environ.get("TASK_COEVOLVE_ENABLED", "1") != "0"
TASK_COEVOLVE_RHO = float(os.environ.get("TASK_COEVOLVE_RHO", "0.5"))   # fracción del pool
TASK_COEVOLVE_L = float(os.environ.get("TASK_COEVOLVE_L", "0.125"))     # suelo ℓ (nunca evaluadas)
TASK_COEVOLVE_LAMBDA = float(os.environ.get("TASK_COEVOLVE_LAMBDA", "0.025"))  # λ/√n
TASK_COEVOLVE_MC_REPS = int(os.environ.get("TASK_COEVOLVE_MC_REPS", "4000"))   # reps Monte Carlo para π_t
TASK_COEVOLVE_SEED = int(os.environ.get("TASK_COEVOLVE_SEED", "13"))

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