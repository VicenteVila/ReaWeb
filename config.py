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
    "stagnation_hard_stop": 7,
    "min_improvement_percent": 2.0,
}

CONTEXT_DEFAULTS = {
    "compaction_threshold_tokens": 60000,
    "max_history_turns": 8,
    "lessons_max_items": 12,
    "search_tree_max_nodes": 15,
}


def ensure_dirs() -> None:
    for p in PATHS.values():
        p.mkdir(parents=True, exist_ok=True)