# Changelog

Todas las versiones notables de ReaWeb. El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added

- **Graph Engineering** (Punto 12 — Feng et al., "Graph Engineering in the Era
  of LLM Agents", 2026; ver `Docs/GRAPH_ENGINEERING.md`): tres primitivas
  estructurales adaptadas de la capa de sistema del paper a un arnés de agente
  único:
  - **Grafo de dependencias de capacidades** (Graph of Skills, §3.3):
    `domain/generated/skill_deps.yaml` + `tools/domain/skill_graph.py` — aristas
    `depends_on`/`inhibits`/`repeat_guard` entre tools; las violaciones
    observadas en la secuencia real de la run se inyectan como advertencias en
    el estado del agente (bloque "🕸 Grafo de dependencias"). Punto 12b:
    `deps_pending()` añade un bloque "PASOS PENDIENTES" predictivo que avisa
    *antes* de que el agente ejecute una tool sin prerequisitos cumplidos.
  - **Atribución causal de fallos** (Who&When / MAST, §4.4.2):
    `detect_root_cause()` mapea el eje más débil bajo umbral a un enum cerrado
    (`visual_alignment`, `creative_stale`, `functional_broken`, ...) y viaja en
    el nodo del árbol y el estado ("Causa dominante — ataca la raíz, no el
    síntoma"); el acceptance gate clasifica sus rechazos como `unmeasurable`,
    `no_improvement` o `dev_degradation` en `harness_edits.root_cause`, con
    agregación vía `rejected_causes_summary()`.
  - **Genealogía de meta-ediciones** (EvoFlow / gobernanza estructural, §4.5 y
    §5.2): `harness_edits.parent_id` enlaza cada propuesta con la última edición
    aceptada del mismo fichero; `edit_genealogy(id)` (CTE recursiva) devuelve la
    cadena raíz→hoja para podar líneas que mutan sin mejorar.
- **Pipeline de diseño** (Punto 11 — calidad estética de los artefactos):
  - **Críticos VLM sin caché**: `generate_vision(use_cache=False)` en
    `audit_visual`/`audit_creative` — el embedding semántico del key colisionaba
    entre screenshots distintos (hash de imagen = 16 hex chars en un payload casi
    idéntico) y devolvía la crítica de una iteración anterior, cegando el loop
    estético (una entrada vision acumuló 18 hits con críticas idénticas en T1-T9).
  - **Feedback estructurado al generador**: `metrics_block` transporta listas
    cortas de strings; `audit_page` emite `fails` (fallos del evaluador), los
    críticos emiten `vlm_issues`/`vlm_suggestions`; el estado del agente los
    muestra como objetivo obligatorio de la siguiente mutación.
  - **Sistemas de diseño reales por arquetipo**: sección `design_system` en los
    7 `rules.yaml` (paleta, Google Fonts, escala tipográfica, tratamientos de
    hero, microinteracciones alineadas con el eje `visual`) y `stack.json`
    reescritos al stack real (vanilla HTML/CSS/JS, sin build step) — se elimina
    la ficción Next.js/Tailwind que el generador no podía usar.
  - **Seed CSS**: H0 parte de `templates/static/` (design tokens + base
    accesible + utilidades reveal/sticky/reduced-motion) en vez de una página
    en blanco.
- **Selección adaptativa de tareas de validación** (Punto 10 — "Task-CoEvolve",
  Miyai et al., arXiv:2608.20169): motor `tools/domain/task_coevolve.py` con
  pesos de varianza histórica del score (adaptación continua de la Eq. 2),
  muestreo sin reemplazo ponderado determinista (Efraimidis-Spirakis), π_t por
  Monte Carlo y estimadores Hájek / diferencia anclada (Eqs. 3-4) con la regla
  de elección del §3.3.
- **Tabla `task_evals`** en `memory/memory.db` (`agent/memory_db.py`): una fila
  por tarea evaluada (task_hash, score, baseline, harness_hash); alimenta las
  futuras selecciones y sirve de historial fino del benchmark.
- **Suite con presupuesto** (`scripts/run_benchmark.py`): flags `--rho X`
  (default 0.5) y `--full`; con rho<1 solo se ejecuta el subconjunto muestreado
  y el leaderboard reporta Ŝ full-suite estimada junto a la media cruda. Cada
  tarea ejecutada se registra en `task_evals`. CI anclado a `--full` para que
  el leaderboard siga siendo comparable entre commits.
- **Gate adaptativo** (`scripts/gate_harness_edit.py`): las train/dev fijas se
  sustituyen por las 2 tareas más discriminativas según varianza histórica;
  `--fixed-tasks` restaura el comportamiento antiguo.
- **Pool ampliado**: `benchmark/tasks.yaml` pasa de 7 a **14 tareas** (dos por
  arquetipo) para que el muestreo adaptativo sea estadísticamente significativo.
- Config `TASK_COEVOLVE_ENABLED/RHO/L/LAMBDA/MC_REPS/SEED` en `config.py`;
  tests en `test/test_task_coevolve.py` (15, sin API key); documentación en
  `Docs/TASK_CO_EVOLUTION.md`.

### Fixed

- **Crash en `_run_suite`** (`scripts/run_benchmark.py`): `agent.model` no
  existe en `Agent` → ahora se lee `agent.llm.model`.
- **Contaminación de benchmark por caché semántica**: la suite con fallback a
  flash-lite reciclaba respuestas por similitud de coseno (una entrada alcanzó
  178 hits) y las runs degeneraban en 1-2 tool calls. Nuevo flag
  `--no-cache` en `run_benchmark.py` (`use_cache=False` en `run_single`) para
  que el benchmark mida el harness y no la caché.
- **Hueco del write-gate en meta-evolución**: `edit_skill` no pasaba por
  gobernanza y su modo `append` concatenaba prosa cruda (contaminación real en
  `landing-page/rules.yaml`: párrafo sobre portfolios dentro del arquetipo
  equivocado). Ahora el YAML resultante debe tener forma declarativa estricta
  (mapping de mappings/listas, strings-valor cortos y mono-línea); limpieza de
  la contaminación existente. Ver `Docs/EVOLUTION.md` §gobernanza.

## [0.2.0] - 2026-08-18

Versión con control de versiones (tags + releases), CLI simplificada, Docker,
empaguetado y capa de gobernanza de skills.

### Added

- **Gobernanza de skills / misevolution** (Punto 9 — "Practice Makes Unsafe",
  Mao et al., 2026): write gate (`tools/domain/skill_auditor.py` + deleter
  delete-only), retrieval gate (`safe_only=True`), reuse gate (SAFEEVOLVE:
  `record_reuse` + retirement). Benchmark M/B/P de simulacro marcado
  (`benchmark/misevo_tasks.yaml`, `scripts/run_misevo.py`) y CI
  (`.github/workflows/misevo.yml`).
- **Caché semántica de LLM** (Punto 2): `.agent/llm_cache.py` con índice FAISS +
  embeddings, umbral 0.80, TTL 7 días, flag `--no-cache`.
- **Sandbox de ejecución de código** (Punto 8): allowlist de módulos Python +
  chequeo AST; bash con blocklist y `prlimit` (512 MiB / 10 s / 32 proc).
- **Benchmark + leaderboard** (Punto 7): `benchmark/tasks.yaml`, flags
  `--suite`/`--leaderboard`, CI con commit automático
  (`.github/workflows/leaderboard.yml`).
- **CLI simplificada** (`reaweb`): entry point con la experiencia "prompt y
  obtén tu web" y modo `--quick` (presupuesto mínimo, sin meta-evolución ni
  críticos VLM).
- **Docker**: `Dockerfile` + `.dockerignore` para ejecutar sin configurar el
  entorno local.
- **Releases**: `CHANGELOG.md`, workflow `.github/workflows/release.yml` para
  generar tags + GitHub Release automáticamente.
- **Contribución**: `CONTRIBUTING.md` y templates de issues (bug/feature).
- **Docs**: citación formal del estudio de misevolution en `READAPTATION.md`
  (sección 3), `EVOLUTION.md` §2.11, `REASONING.md` (hito 14), tarjetas
  visuales `.jfif`.

### Changed

- Versionado semántico: `pyproject.toml` pasa a `0.2.0` (0.x = prototipo de
  investigación, API aún no estable) con `[project.scripts]` y metadatos de
  licencia/readme.
- Presupuesto por defecto de la suite de investigación en el CLI:
  16 turnos / $5.00; modo `--quick`: 4 turnos / $0.50.

### Fixed

- Rutas de las imágenes demo en `README.md` (`Docs/demo/`, no `docs/demo/`) —
  GitHub es case-sensitive y no renderizaba las capturas.
- Test de CI `test_evolution.py::test_snapshot_includes_docs_and_memory`:
  validaba ambos casos (con/sin `memory/lessons.db` en el snapshot) para
  checkouts limpios.
- `numpy` fijado a `<2.2` (2.4.6 rompía `import numpy` en WSL por la librería
  `libscipy_openblas64`).

## [0.1.0] - 2026-08-15

Scaffold inicial del harness ReASearch/AutoDesign para desarrollo web.

### Added

- Agente autónomo (`Agent.run`): bucle de hipótesis H0..Hn con árbol de
  búsqueda (`SearchTree`), sin controlador externo.
- Tools de dominio: `generate_candidate` (subagente), `audit_page`,
  `analyze_project`, `fetch_url`, `fetch_readme`, `fetch_repo_topics`,
  `update_lessons`, `select_final`, `revert_workspace`, `edit_skill`,
  `review_harness`, `deploy_preview`, `git_snapshot`.
- Evaluador multi-eje (SEO, A11y, Performance, Responsive, Best Practices,
  structure, task, visual) con gates P0 y `BLOCKING_CEILING`.
- Críticos VLM: `audit_visual`, `audit_creative`, `audit_truth` con
  `blend_visual_total`.
- Juicio de verdad funcional: test Chrome headless real (`functional_tester`).
- Memoria persistente en SQLite (`lessons.db`): `worked/didnt/try`,
  auto-lecciones por delta (`LESSON_AUTO`), experiments, runs.
- Meta-evolución sobre `domain/` con `HARNESS_COMPONENTS`, snapshot y
  `harness_diff` por run.
- Loop de subtareas (F1), explorar→explotar (A2/B3/C5) y señal `novelty`.
- `scripts/run_benchmark.py`, `scripts/trend_evolution.py`,
  `scripts/gen_cards.py`, `scripts/render_dashboard.py`.
- CI (`.github/workflows/ci.yml`), `docs/demo`, tarjetas didácticas PNG.