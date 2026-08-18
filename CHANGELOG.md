# Changelog

Todas las versiones notables de ReaWeb. El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

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