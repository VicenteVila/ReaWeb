# reaweb-harness

Agente **ReASearch** de optimización web: dado un arquetipo y una tarea, desarrolla
páginas web iterativamente (genera candidato → audita → mejora) y, además,
**evoluciona su propio harness** (reglas, skills y workflows en `domain/`).

Basado en:

- **ReASearch** ("The Optimizer Is the Agent: Reasoning-Driven Search across Prompts,
  Programs, and ML Workflows") — el agente es el optimizador: sin loop externo,
  re-emisión de estado cada turno, memoria persistente y meta-evolución.
- **Propuesta Arquitectura de Agente Web** — diseño de carpetas, stack y estrategia
  free-tier.
- **Docs/** — reglas globales, skills, workflows y 6 arquetipos de web development.

## Stack

- Python 3.12, `google-genai` (Gemini), Pydantic, Jinja2, YAML.
- Modelo por defecto: `gemini-3.1-pro-preview` con **fallback automático** a
  `gemini-3.1-flash-lite` → `gemini-3-flash-preview` si la quota free-tier se agota.
- Evaluador ligero (sin Chrome): scores SEO, A11y, Performance, Responsive,
  Best Practices (0-100).

## Instalación

```bash
cd reaweb-harness
pip install google-genai pydantic PyYAML jinja2
cp .env.example .env   # edita GEMINI_API_KEY
```

## Uso

```bash
# run básica
python -m scripts.run_agent \
  --archetype landing-page \
  --task "landing page para un SaaS de analítica de IA" \
  --turns 8

# con URL de referencia (analiza su HTML y adapta el contenido como H0)
python -m scripts.run_agent \
  --archetype landing-page \
  --url "https://www.introw.io/" \
  --task "landing SaaS adaptada de introw.io al contenido de github.com/VicenteVila" \
  --turns 16 --target-h 3

# otros arquetipos: ecommerce, corporate-business, saas-dashboard,
# portfolio-creative, blog-content
```

Opciones: `--model`, `--turns`, `--max-cost`, `--no-meta` (deshabilita meta-evolución),
`--target-h N` (objetivo mínimo de hipótesis, p. ej. `--target-h 3` exige generar y
auditar H0..H3 antes de poder cerrar), `--url <URL>` (URL de referencia a analizar:
la tool `fetch_url` descarga su HTML crudo, lo guarda en la run y el generador la usa
como referencia de estructura/estética para H0, adaptando el contenido a la tarea).

### Flujo (UX)

```
H0 → el agente genera el primer candidato y lo audita (baseline)
H1, H2, ... → el agente razona, edita con generate_candidate y re-audita
Final → select_final exporta el mejor candidato razonando sobre la historia
```

Si se pasa `--url`, el agente invoca `fetch_url` antes de generar H0 para analizar
la web de referencia y adaptar su estructura/estética al contenido de la tarea.

Cada run deja en `runs/<timestamp>--<arquetipo>/`:

- `transcript.jsonl` — interacción completa (tools + evaluaciones)
- `search_tree.json` — árbol de hipótesis H0..Hn con métricas, parents y status
- `candidates/H<i>/` — snapshot congelado de cada hipótesis (generado automáticamente)
- `screenshots/H<i>.png` — render de cada hipótesis (dashboard)
- `final/` — mejor candidato exportado (aunque `select_final` no se llame)
- `lessons_incremental.md` — espejo en markdown de las lecciones de la run
- `reference/` — HTML crudo descargado de la URL de referencia (`--url`), si se usó

### Análisis de URLs de referencia

Con `--url <URL>`, la tool **`fetch_url`** descarga el HTML crudo de una web, lo
guarda en `runs/<run_id>/reference/` (y `workspace/reference.html` para el
generador) y devuelve al agente un extracto analizado (title, meta, headings,
nav, contenido, clases). El generador incluye la referencia en su prompt para
que H0 adapte **estructura y estética** de la URL a la tarea, sin copiar su
contenido literal. Se registra `initial_url` en `run_config.json` y en la DB.

La memoria persistente vive en SQLite (`memory/memory.db`, stdlib, sin
dependencias): tablas `runs`, `lessons`, `experiments` y `tree_nodes`. El agente
escribe/lee de la DB; los `.md` son solo export legible para humanos.

### Evaluación visual

```bash
python -m scripts.render_dashboard                # todas las runs
python -m scripts.render_dashboard --run <run_id> # una run concreta
```

Genera un `dashboard_<ts>.html` autocontenido (SVG + imágenes base64, sin
dependencias externas): curva H0→Hn, filmstrip con screenshots de cada hipótesis,
radar del mejor vs baseline y tabla de métricas (incluye columnas `visual` y `task`).
Con `--run <run_id>` el dashboard se escribe **dentro de esa run**
(`runs/<run_id>/dashboard_<ts>.html`); sin `--run`, en la raíz de `runs/`.
Renderiza con Chrome de Windows headless vía WSL (`wslpath -w`); si no lo
encuentra, genera el dashboard solo-datos.

## Scripts

| Script | Función |
|---|---|
| `scripts/run_agent.py` | Ejecuta una run de optimización end-to-end |
| `scripts/seed_from_docs.py` | Regenera `domain/` desde `../Docs/` |
| `scripts/merge_lessons.py` | Fusiona lecciones de runs al archivo global |
| `scripts/backfill_memory.py` | Migra runs existentes de `runs/` a `memory/memory.db` |
| `scripts/cleanup_runs.py` | Limpieza de `runs/` (--keep N, --archive, --prune-*) |
| `scripts/export_candidate.py` | Exporta el candidato final a un destino |
| `scripts/render_dashboard.py` | Dashboard visual de evolución (curvas, filmstrip, radar) |

## Memoria y limpieza de runs

La memoria del agente se persiste en **SQLite** (`memory/memory.db`):

- `runs` — metadatos de cada run (arquetipo, task, modelo, started/finished, mejor score/nodo)
- `lessons` — lecciones (category worked/didnt/try), deduplicadas por contenido
- `experiments` — historial de llamadas a tools con resultado y delta
- `tree_nodes` — árbol de hipótesis H0..Hn (mismo contenido que `search_tree.json`)

Los ficheros markdown (`lessons.md`, `lessons_incremental.md`) quedan como export
legible; la fuente de verdad es la DB. Al crear una run, `run_agent` registra la
run en la DB; al cerrar, actualiza `finished`, `best_score` y `best_node`.

**Migración de historial existente:**

```bash
python -m scripts.backfill_memory                  # migra todas las runs de runs/
python -m scripts.backfill_memory --run <run_id>   # solo una
```

**Limpieza de la carpeta `runs/`** (que acumula runs y dashboards):

```bash
python -m scripts.cleanup_runs --keep 6 --prune-dashboards --prune-orphans   # dry-run (default)
python -m scripts.cleanup_runs --keep 6 --prune-dashboards --prune-orphans --yes
python -m scripts.cleanup_runs --keep 6 --archive /tmp/backup --yes   # empaca en tar.gz
```

- `--keep N` borra las runs más antiguas conservando las N recientes (solo si ya
  están en la DB — corre `backfill_memory` primero).
- `--prune-dashboards` elimina los `dashboard_*.html` sueltos en la raíz de
  `runs/` (artefactos viejos, regenerables con `render_dashboard --run`).
- `--prune-orphans` elimina el `runs/lessons_incremental.md` raíz ya migrado.
- `--archive DIR` mueve las runs a borrar a un `.tar.gz` en vez de eliminarlas.

## Estructura

```
.agent/       Loop del agente (agent.py, llm.py, state.py, memory_db.py, budget_tracker.py, prompts/)
tools/        Tools invocables (file_io, code_exec, domain/)
domain/       Conocimiento: reglas, skills, workflows, arquetipos (semilla de Docs/)
memory/       memory.db (fuente de verdad) + lessons.md (export)
runs/         Un directorio por run
workspace/    Sandbox (workspace/current = candidato activo)
config/       agent/budget/tools yaml
scripts/      Entrypoints
test/         Tests (evaluador, fixtures)
```

## Docs/ vs domain/ (separación de fuentes)

- **`Docs/`** (`../Docs`, fuera del repo) es la **especificación inicial** escrita
  por humanos: `global_rules.md`, `agent_skills.md`, `global_workflows.md` y
  `Archetypes/<arquetipo>/{project-context,project-rules,project-workflows}.md`
  (+ `tech-stack.json`). Es la semilla que se importa **una sola vez** con
  `scripts/seed_from_docs.py`, que la convierte a YAML/JSON en `domain/`.
- **`domain/`** es el **conocimiento vivo**: el agente lo mejora vía meta-evolución
  (`edit_skill`/`review_harness`, restringidos a `domain/`). Lo que el harness
  aprende durante las runs se aplica aquí, **no** en `Docs/`.
- Por tanto `Docs/` puede quedar **obsoleto** respecto a `domain/` (p. ej. el
  arquetipo `knowledge-graph` existe en `domain/` pero no en `Docs/`). Si se
  quiere actualizar la especificación humana, hay que re-sincronizarla
  manualmente desde `domain/` (no hay script inverso automático).

Para que esta separación sea **medible**, el snapshot del harness
(`agent/harness_snapshot.py`) incluye **tanto `Docs/` como `domain/`** además de
las lecciones de la DB: cualquier cambio en la fuente semilla, en el conocimiento
vivo o en la memoria altera el `harness_hash` de la run y queda visible en
`scripts/trend_evolution.py`.

## Meta-evolución

El agente puede editar su propio harness a través de `edit_skill` (validación YAML
incluida). Ejemplo verificable:

```python
from tools.domain.meta_editor import EditSkill
EditSkill().run(path="archetypes/landing-page/rules.yaml",
                instruction="conversion_rules:\n  - mobile_first",
                mode="replace")
```

## Evaluador y categorías "task" y "visual"

El evaluador ligero (sin Chrome) puntúa SEO, A11y, Performance, Responsive y
Best Practices (0-100). Además:

- **`task`**: si la tarea estipulada menciona requisitos verificables (repositorios
  de `github.com/usuario`, URLs, nombres de proyectos), `extract_requirements()`
  los extrae automáticamente y el evaluador verifica que aparezcan literalmente en
  el código (html+css+js). Evita optimizar el score a costa de la tarea real.
- **`visual`**: proxy de diseño moderno/interactivo que exige efectos REALES, no
  menciones: canvas animado (requestAnimationFrame + dibujo, sin canvas "muerto"),
  `@keyframes` usado por `animation`, gradientes en propiedades (no en
  comentarios), `transition` con disparador real (`:hover`/`:focus`/`:active`),
  dark mode vía `prefers-color-scheme`/`matchMedia`, tema persistido en
  localStorage, scroll-reveal con IntersectionObserver/listener, `prefers-reduced-motion`,
  hover effects, nav sticky, microinteracciones (tilt/mousemove).

`total` = media **ponderada** de (seo, a11y, perf, resp, bp, visual) y +`task`
si hay requirements. `visual` pesa **2.0×** (configurable en `WEIGHTS`).
Responsive y Best Practices se evalúan contra el contenido combinado
(html+css+js), no solo contra el HTML.

## Tests

```bash
python3 -m pytest test          # si tienes pytest
python3 -c "import sys; sys.path.insert(0,'.'); from test.test_evaluator import *; test_good_scores_high(); test_bad_scores_low(); test_visual_high_with_modern_design(); test_task_requirements_present(); print('OK')"
```

## Notas

- El evaluador ligero mide métricas estáticas (no Core Web Vitals reales). Migrar a
  Lighthouse CI queda como mejora futura.
- La API key vive solo en `.env` (gitignored). Nunca se hardcodea en el código.