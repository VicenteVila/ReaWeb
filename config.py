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

# Proveedor LLM: "gemini" (SDK nativo) o cualquiera de los OpenAI-compatible de
# OPENAI_COMPAT_PROVIDERS (mistral / groq / cerebras / openrouter). El agente
# (tool-calling) usa el modelo de texto y los críticos VLM el de visión.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
# Proveedor solo para los críticos VLM (screenshots), si conviene separarlo del
# agente: p. ej. Groq para el texto (rápido, buen tool-calling) y Mistral para
# la visión (sus screenshots completos no chocan con el límite ITPM de Groq).
# Vacío = usar el mismo proveedor que el agente.
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "").strip().lower()
# LLM_SINGLE_MODEL=1: colapsa la cadena de fallback al modelo base. Para
# baterías A/B de integridad estricta (un solo modelo resuelto en todo el
# dataset, sin contaminación pro->lite cuando agota la cuota). El crítico VLM
# NO se ve afectado (su modelo se configura aparte).
LLM_SINGLE_MODEL = os.environ.get("LLM_SINGLE_MODEL", "").strip().lower() in ("1", "true", "yes")


def _openai_compat(key_env, base_env, base_default, model_env, model_default,
                   vision_env, vision_default, fallbacks, extra_headers=None):
    """Ficha de un proveedor con API OpenAI-compatible (chat/completions)."""
    return {
        "key_env": key_env,
        "api_key": os.environ.get(key_env, ""),
        "base_url": os.environ.get(base_env, base_default),
        "model": os.environ.get(model_env, model_default),
        "vision_model": os.environ.get(vision_env, vision_default),
        "fallbacks": fallbacks,
        "headers": extra_headers or {},
    }


OPENAI_COMPAT_PROVIDERS = {
    # Mistral: el tier gratuito solo expone los 8B (ministral) y pixtral-12b;
    # mistral-large/pixtral-large responden 403/429 en esa clave.
    "mistral": _openai_compat(
        "MISTRAL_API_KEY", "MISTRAL_BASE_URL", "https://api.mistral.ai/v1",
        "MISTRAL_MODEL", "open-mistral-nemo",
        "MISTRAL_VISION_MODEL", "pixtral-12b",
        ["mistral-tiny"],
    ),
    # Groq:texto gpt-oss-120b (tool-calling nativo, muy rápido) y VLM
    # qwen3.8-27b (sí acepta imagen; gpt-oss es solo texto).
    "groq": _openai_compat(
        "GROQ_API_KEY", "GROQ_BASE_URL", "https://api.groq.com/openai/v1",
        "GROQ_MODEL", "openai/gpt-oss-120b",
        "GROQ_VISION_MODEL", "qwen/qwen3.8-27b",
        ["qwen/qwen3.8-27b"],
    ),
    "cerebras": _openai_compat(
        "CEREBRAS_API_KEY", "CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1",
        "CEREBRAS_MODEL", "gpt-oss-120b",
        "CEREBRAS_VISION_MODEL", "qwen-3.8-27b",
        ["qwen-3.8-27b"],
    ),
    "openrouter": _openai_compat(
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1",
        "OPENROUTER_MODEL", "google/gemini-3.1-pro-preview",
        "OPENROUTER_VISION_MODEL", "google/gemini-3.1-pro-preview",
        [],
        {"HTTP-Referer": "https://reaweb.local", "X-Title": "ReaWeb harness"},
    ),
}

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

# Versión de la escala de `total`. Súbela cuando cambie QUÉ mide o cómo se
# combinan los ejes (pesos, gates, ejes nuevos). El harness la graba en cada
# evaluación y Task-CoEvolve filtra el historial por versión, de modo que los
# scores de una escala antigua no se mezclan con los de la nueva al calcular
# varianzas para la selección adaptativa de tareas.
#
# v2 (2026-09-29): el funcional se mide servriendo por HTTP en vez de file://,
# `grafo_visible` cuenta de verdad y un test P0 fallado capa el score. Los
# totales previos a v2 se medían con el grafo roto (fetch bloqueado por CORS
# bajo file://) y NO son comparables con los de v2.
SCORING_VERSION = 2

# Umbral de ceiling para candidatos que incumplen un gate bloqueante (Eq. 8 del
# paper: un P0 gate capa la puntuación). Si un candidato no cumple las secciones
# obligatorias de la tarea, su total no puede superar este techo.
BLOCKING_CEILING = 40

# Gate funcional (P0). Además del umbral agregado, estos tests son gates por
# sí mismos: si alguno falla, el candidato queda capado aunque la media
# funcional sea alta. Así una media no puede tapar "el grafo no se dibuja" o
# "el JS está roto" (el caso que dejó pasar páginas rotas con total alto).
FUNCTIONAL_P0_GATE = ["js_sin_errores", "interactivos_responden", "grafo_visible"]

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

# Verificador de pasos (L0): tras cada generate_candidate se comprueban
# invariantes LOCALES (gratis, sin llamadas LLM). Si fallan, el harness restaura
# el workspace desde la última snapshot verificada y el agente reintenta desde un
# estado bueno, con escalada y cierre honesto si se repite. 100% simétrico en
# ambos brazos del A/B (no puede favorecer una condición).
VERIFIER_ENABLED = os.environ.get("VERIFIER_ENABLED", "1") != "0"
VERIFIER_CHECK_RENDER = os.environ.get("VERIFIER_CHECK_RENDER", "1") != "0"
# rechazos consecutivos: a partir de este nivel se escala (objetivo de reparación,
# estilo auto_unblock); igual o por encima de este nivel, la run se detiene
# honestamente en vez de seguir quemando turnos/cuota sobre un workspace roto.
VERIFIER_MAX_REJECT_BEFORE_ESCALATE = int(os.environ.get(
    "VERIFIER_MAX_REJECT_BEFORE_ESCALATE", "2"))
VERIFIER_MAX_REJECT_BEFORE_STOP = int(os.environ.get(
    "VERIFIER_MAX_REJECT_BEFORE_STOP", "3"))

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
    "openai/gpt-oss-120b": (0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "qwen/qwen3.8-27b": (0.20, 0.60),
    "qwen-3.8-27b": (0.20, 0.60),
    "gpt-oss-120b": (0.15, 0.75),
    "mistral-large-latest": (2.00, 6.00),
    "pixtral-large-latest": (2.00, 6.00),
    "open-mistral-nemo": (0.15, 0.15),
    "pixtral-12b": (0.15, 0.15),
    "mistral-small-latest": (0.10, 0.30),
    "mistral-tiny": (0.10, 0.30),
    "default": (1.25, 5.00),
}


def ensure_dirs() -> None:
    for p in PATHS.values():
        p.mkdir(parents=True, exist_ok=True)