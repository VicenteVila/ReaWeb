# READAPTATION — Adaptación de ReASearch a ReaWeb

Este documento describe el esfuerzo de **readaptación** de los algoritmos y
conceptos del trabajo original en el que se basa ReaWeb al dominio del desarrollo
web, y cita formalmente dicho trabajo. Es documentación para humanos.

---

## 1. Trabajo original (citación)

> **The Optimizer Is the Agent: Reasoning-Driven Search across Prompts,
> Programs, and ML Workflows.**
>
> Junbo Li, Boyi Liu, Canwen Xu, Yite Wang, Yuxiong He, Zhangyang Wang,
> Qiang Liu, Zhewei Yao.
>
> COLM 2026. arXiv:2608.06714 [cs.AI] (v1, 7 Aug 2026).
>
> doi: [10.48550/arXiv.2608.06714](https://doi.org/10.48550/arXiv.2608.06714)

### Formato BibTeX

```bibtex
@inproceedings{li2026optimizer,
  title     = {The Optimizer Is the Agent: Reasoning-Driven Search across
               Prompts, Programs, and ML Workflows},
  author    = {Li, Junbo and Liu, Boyi and Xu, Canwen and Wang, Yite
               and He, Yuxiong and Wang, Zhangyang and Liu, Qiang and Yao, Zhewei},
  booktitle = {Conference on Language Modeling (COLM)},
  year      = {2026},
  eprint    = {2608.06714},
  archivePrefix = {arXiv},
  primaryClass = {cs.AI},
  doi       = {10.48550/arXiv.2608.06714},
  url       = {https://arxiv.org/abs/2608.06714}
}
```

### Formato APA

> Li, J., Liu, B., Xu, C., Wang, Y., He, Y., Wang, Z., Liu, Q., & Yao, Z. (2026).
> *The Optimizer Is the Agent: Reasoning-Driven Search across Prompts, Programs,
> and ML Workflows*. COLM 2026. https://doi.org/10.48550/arXiv.2608.06714

---

## 2. Qué tomamos del paper, con fidelidad

El paper propone un **scaffold único de agente** donde el LLM decide qué
evaluar, cómo diagnosticar, qué editar y cuándo verificar o revertir, usando
herramientas de dominio y **memoria persistente**, sin controlador externo.
ReaWeb conserva ese diseño central:

| Concepto del paper | Implementación en ReaWeb |
|---|---|
| El agente es el optimizador (sin loop externo) | `Agent.run()` en `.agent/agent.py:322` — el agente decide su próxima acción cada turno |
| Operaciones de optimización empaquetadas como tools | `generate_candidate`, `audit_page`, `analyze_project`, `edit_skill`, `python_exec`, `fetch_url`, `fetch_readme`, `fetch_repo_topics` (`tools/`) |
| Memoria persistente con esquema worked / didnt / try | tabla `lessons` (`category`, `.agent/memory_db.py:31`) + `_parse_lesson_blocks` (`.agent/state.py`) |
| Búsqueda por hipótesis con relaciones de parentesco | `SearchTree` / `TreeNode` (`.agent/state.py:15,24`), `_handle_eval_result` (`.agent/agent.py:246`) |
| Doble verificación de ganancias prometedoras | `audit_page` confirma la hipótesis actual sin crear nodos duplicados (`.agent/agent.py:287`) |
| Reversión de ramas improductivas | estados `best_branch` / `dead_end` en el árbol (`.agent/state.py`) |
| Explotación adaptativa bajo presupuesto | `BudgetTracker` con avisos de estancamiento y parada dura (`.agent/budget_tracker.py:41,70`) |
| Evaluación con tools de dominio | evaluador estático ligero (`tools/domain/evaluator.py:422`) |
| Reuso de lecciones previas entre runs | `read_global_lessons()` inyectado en `state_template.j2` |
| Compactación de contexto en horizontes largos | `ContextManager` (`.agent/state.py`) |

## 3. Qué readaptamos al dominio web y por qué

La readaptación fue el trabajo principal: el scaffold es genérico, pero el
dominio (páginas web estáticas, evaluables sin navegador) exige herramientas,
métricas y reglas propias.

| Adaptación | Detalle | Justificación |
|---|---|---|
| **Evaluador ligero sin Chrome** | Scores 0-100 por categoría sobre html+css+js estáticos (`evaluator.py:422`) | Coste cero de infraestructura/latencia; suficiente para comparar hipótesis. Reemplazable por Lighthouse CI. |
| **Categoría `task`** | `extract_requirements()` extrae repos/URLs/nombres de la tarea y verifica su presencia literal (`evaluator.py:241`) | El paper optimiza contra un objetivo definido; aquí el "objetivo" es la tarea estipulada, y un score alto sin cumplirla es fracaso. |
| **Categoría `structure`** | Lista de secciones obligatorias verificadas en el HTML (`evaluator.py`, `extract_sections`) | Cierra el "trampa" de rellenar checks técnicos sin construir la landing que pide la tarea. |
| **Proxy `visual` (peso 2.0)** | Exige efectos REALES: canvas animado dinámico, `@keyframes` usado, `transition` con `:hover/:focus/:active`, gradientes en propiedades, dark mode persistido (`evaluator.py:83,410`) | Traduce "diseño moderno" (no directamente optimizable) a señales verificables sin navegador, y evita que un canvas "muerto" cuente. |
| **Principio anti-trampa** | `system_base.txt:24` — "El score agregado es una SEÑAL, no el objetivo" | El paper muestra agentes que rellenan heurísticas; lo traducimos a regla de prompting explícita. |
| **Memoria en SQLite** | Tablas `runs`, `lessons`, `experiments`, `tree_nodes` (stdlib `sqlite3`) | El paper usa memoria persistente; elegimos DB (no markdown) para deduplicar y consultar. |
| **Meta-evolución sobre `domain/`** | `edit_skill`/`review_harness` validan YAML y restringen el path (`tools/domain/meta_editor.py:46`) | El paper observa que el agente "refina su estrategia" — aquí refinamos reglas declarativas verificables, no el código del loop. |
| **`fetch_repo_topics` (categorías arXiv)** | Clasifica cada repo en categorías sujet arXiv (`cs.AI`, `cs.CL`, ...) desde su README (`tools/domain/repo_topics.py`) | Aportación propia de dominio: materializar un "grafo de conocimientos" con datos reales de los repos. |
| **`fetch_readme` / `fetch_url`** | Descarga READMEs y HTML de referencia para adaptar estructura/estética (`readme_fetcher.py`, `web_generator.py`) | Enriquecer la entrada del generador sin copiar contenido literal. |

### Divergencias conscientes del paper

- **El paper optimiza el *objetivo* del LLM estudiante; ReaWeb optimiza el
  *artefacto web***. El evaluador es un proxy determinista y barato en vez de un
  jurado LLM, por coste y reproducibilidad. Eso pierde riqueza semántica, pero
  gana determinismo y hace la optimización trazable.
- **El paper deja que la política emerja libremente; ReaWeb añade refuerzos
  explícitos** (anti-trampa, `target_h`, secciones obligatorias). Es una
  intervención de dominio: el paper no asume una tarea de "rellenar secciones",
  nosotros sí.
- **Meta-evolución medible**: añadimos `harness_snapshot`, `task_hash`, delta y
  trend (ver `EVOLUTION.md`). El paper estudia el comportamiento, no exige
  medir la evolución del propio agente entre runs.

## 4. Esfuerzo de readaptación (resumen)

El trabajo no fue "copiar el loop": fue **mapear cada abstracción del paper a un
mecanismo de dominio verificable**, y añadir capas anti-trampa iterativamente.
El historial de los commits lo refleja: primero el scaffold genérico, después la
categoría `task`, el eje `visual` con efectos reales, la memoria en SQLite, el
evaluador anti-trampa, el grafo de conocimientos y, finalmente, la medición de la
propia evolución. Ver `REASONING.md` para el detalle cronológico.

## 5. Transferencia de aprendizajes del paper al harness

El paper identifica patrones emergentes (doble verificación, reuso de fallos,
revert, exploración adaptativa). En ReaWeb esos patrones se convierten en
**reglas explícitas del harness** (principios 3, 4, 5, 6 de `system_base.txt`) y
en **mecanismos codificados** (`audit_page`, árbol de hipótesis, presupuesto).
Este ciclo —observación del paper → patrón → regla en `domain/`— es el mismo
que el agente debe reproducir en cada run (ver `EVOLUTION.md`).