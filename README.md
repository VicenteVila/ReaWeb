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

# otros arquetipos: ecommerce, corporate-business, saas-dashboard,
# portfolio-creative, blog-content
```

Opciones: `--model`, `--turns`, `--max-cost`, `--no-meta` (deshabilita meta-evolución),
`--target-h N` (objetivo mínimo de hipótesis, p. ej. `--target-h 3` exige generar y
auditar H0..H3 antes de poder cerrar).

### Flujo (UX)

```
H0 → el agente genera el primer candidato y lo audita (baseline)
H1, H2, ... → el agente razona, edita con generate_candidate y re-audita
Final → select_final exporta el mejor candidato razonando sobre la historia
```

Cada run deja en `runs/<timestamp>--<arquetipo>/`:

- `transcript.jsonl` — interacción completa (tools + evaluaciones)
- `search_tree.json` — árbol de hipótesis H0..Hn con métricas, parents y status
- `candidates/H<i>/` — snapshot congelado de cada hipótesis (generado automáticamente)
- `screenshots/H<i>.png` — render de cada hipótesis (dashboard)
- `final/` — mejor candidato exportado (aunque `select_final` no se llame)
- `lessons_incremental.md` — lecciones de la run (se mergean a `memory/lessons.md`)

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
| `scripts/export_candidate.py` | Exporta el candidato final a un destino |
| `scripts/render_dashboard.py` | Dashboard visual de evolución (curvas, filmstrip, radar) |

## Estructura

```
.agent/       Loop del agente (agent.py, llm.py, state.py, budget_tracker.py, prompts/)
tools/        Tools invocables (file_io, code_exec, domain/)
domain/       Conocimiento: reglas, skills, workflows, arquetipos (semilla de Docs/)
memory/       lessons.md (persistente) + registros
runs/         Un directorio por run
workspace/    Sandbox (workspace/current = candidato activo)
config/       agent/budget/tools yaml
scripts/      Entrypoints
test/         Tests (evaluador, fixtures)
```

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