# READAPTATION — Adaptación de ReASearch y AutoDesign a ReaWeb

Este documento describe el esfuerzo de **readaptación** de los algoritmos y
conceptos de los dos trabajos originales en los que se basa ReaWeb al dominio del
desarrollo web, y cita formalmente ambos. Es documentación para humanos.

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

## 2. Trabajo complementario: AutoDesign (citación)

> **AutoDesign: Meta-Harness Optimization for Long-Horizon Agentic Design.**
>
> Yaxin Luo, Haobin Jiang, Jialv Zou, Xu Huang, Wenhao Yan, Haodong Li,
> Zhengrong Yue, Jing Li, Xiaofu Chen, Xiaohan Zhao, Jiacheng Liu, Jiacheng Cui,
> Zhiqiang Shen, Xiaotong Li.
>
> arXiv:2608.13560 [cs.CV] (v1, 13 Aug 2026). Tech Report.
>
> doi: [10.48550/arXiv.2608.13560](https://doi.org/10.48550/arXiv.2608.13560) ·
> proyecto: <https://autodesign.designanything.ai> ·
> código: <https://github.com/Yaxin9Luo/AutoDesign>

### Formato BibTeX

```bibtex
@misc{luo2026autodesign,
  title        = {AutoDesign: Meta-Harness Optimization for Long-Horizon
                  Agentic Design},
  author       = {Luo, Yaxin and Jiang, Haobin and Zou, Jialv and Huang, Xu
                  and Yan, Wenhao and Li, Haodong and Yue, Zhengrong
                  and Li, Jing and Chen, Xiaofu and Zhao, Xiaohan
                  and Liu, Jiacheng and Cui, Jiacheng and Shen, Zhiqiang
                  and Li, Xiaotong},
  year         = {2026},
  month        = {aug},
  eprint       = {2608.13560},
  archivePrefix = {arXiv},
  primaryClass = {cs.CV},
  note         = {Tech Report},
  doi          = {10.48550/arXiv.2608.13560},
  url          = {https://arxiv.org/abs/2608.13560}
}
```

### Formato APA

> Luo, Y., Jiang, H., Zou, J., Huang, X., Yan, W., Li, H., Yue, Z., Li, J.,
> Chen, X., Zhao, X., Liu, J., Cui, J., Shen, Z., & Li, X. (2026).
> *AutoDesign: Meta-Harness Optimization for Long-Horizon Agentic Design*.
> arXiv. https://doi.org/10.48550/arXiv.2608.13560

### Métricas del estudio que ReaWeb utiliza

AutoDesign formaliza un **harness model-harness** que un meta-optimizador mejora
recursivamente a partir del *rollout feedback*. ReaWeb toma de ese estudio las
métricas y mecanismos siguientes, con sus valores en el paper:

| Métrica / mecanismo del paper | Valor reportado en AutoDesign | Uso en ReaWeb |
|---|---|---|
| Score del sistema sobre **PosterBench Main Track** (100 papers, 5 disciplinas) | **78.32**, +7.45 sobre Claude Design | Sirve de referencia de nivel estético: el objetivo del crítico VLM es 0-100 (misma escala de puntuación). |
| **DesignHarness**: harness aprendido aplicado a 7 configuraciones code-agent | promedio 54.99 → **67.39** (+12.4%) | Justifica que mejorar el harness (no solo el artefacto) produce ganancias sistemáticas: es la tesis de `EVOLUTION.md`. |
| **Bucle autónomo de largo horizonte** | 253 tool calls y 11 editing turns en 40 minutos, **por debajo de $3** | Valida el presupuesto de ReaWeb (turns/coste acotado con `BudgetTracker`). |
| **Evaluación humana** del resultado | calidad media de póster de conferencia; mayor preferencia en estudio ciego | Motivación del crítico VLM como proxy de "calidad percibida" sin jurado humano. |

---

## 3. Qué tomamos del paper (ReASearch), con fidelidad

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

## 4. Qué readaptamos al dominio web y por qué

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
| **Crítico VLM (capa estética de AutoDesign, §3.4)** | Screenshot del candidato → score estético 0-100 + issues/sugerencias (`tools/domain/visual_critic.py`) | Traduce "calidad percibida" (lo que AutoDesign mide con humanos/PosterBench) a una señal barata y acumulable que guía la siguiente mutación. |

### Mapeo de los mecanismos de AutoDesign al harness

| Mecanismo de AutoDesign | Implementación en ReaWeb |
|---|---|
| **Meta-harness optimizer** guía a un code-agent para mejorar el harness con rollout feedback (§2.1, componentes atribuibles) | `HARNESS_COMPONENTS` (`config.py:56`): cada meta-edición apunta a UN componente para mantener crédito atribuible de las ganancias. |
| **Gate bloqueante P0 (Eq. 8)**: un fallo crítico capa la puntuación | `BLOCKING_CEILING = 40` (`config.py:66`) + `_apply_blocking_gates` (`evaluator.py:455`): si un candidato incumple secciones obligatorias, su total no supera 40. |
| **Feedback P0 guía la siguiente mutación** (el harness se mejora con la señal del rollout) | `blend_visual_total` (`evaluator.py:582`): `visual = max(visual_estático, vlm)`; la crítica VLM del candidato actual recombina el total del nodo. |
| **Crítico estético del harness (§3.4)** | `tools/domain/visual_critic.py:1` y `.agent/llm.py:133` (crítico estético del paper AutoDesign). |
| **Pesos por eje** | `WEIGHTS` (`evaluator.py:443`): seo/a11y/performance/responsive/best_practices=1.0, **visual=2.0, structure=2.0**, task=1.0 — el eje estético y el estructural pesan el doble, coherente con el énfasis de AutoDesign en la capa visual. |

### Divergencias conscientes de los papers

- **ReASearch optimiza el *objetivo* del LLM estudiante; ReaWeb optimiza el
  *artefacto web***. El evaluador es un proxy determinista y barato en vez de un
  jurado LLM, por coste y reproducibilidad. Eso pierde riqueza semántica, pero
  gana determinismo y hace la optimización trazable.
- **ReASearch deja que la política emerja libremente; ReaWeb añade refuerzos
  explícitos** (anti-trampa, `target_h`, secciones obligatorias). Es una
  intervención de dominio: el paper no asume una tarea de "rellenar secciones",
  nosotros sí.
- **AutoDesign optimiza el harness para el dominio póster; ReaWeb lo hace para
  el dominio web estático**. ReaWeb conserva la idea (meta-optimización del
  harness con feedback del rollout) pero el "harness" aquí son reglas YAML en
  `domain/` y el feedback es el crítico VLM sobre el candidato real, no un
  Dataset de Posters.
- **Meta-evolución medible**: añadimos `harness_snapshot`, `task_hash`, delta y
  trend (ver `EVOLUTION.md`). Los papers estudian el comportamiento, no exigen
  medir la evolución del propio agente entre runs.

## 5. Esfuerzo de readaptación (resumen)

El trabajo no fue "copiar el loop": fue **mapear cada abstracción de los papers a
un mecanismo de dominio verificable**, y añadir capas anti-trampa iterativamente.
El historial de los commits lo refleja: primero el scaffold genérico, después la
categoría `task`, el eje `visual` con efectos reales, la memoria en SQLite, el
evaluador anti-trampa, el grafo de conocimientos, la medición de la propia
evolución y, finalmente, el crítico VLM como capa estética de AutoDesign. Ver
`REASONING.md` para el detalle cronológico.

## 6. Transferencia de aprendizajes de los papers al harness

ReASearch identifica patrones emergentes (doble verificación, reuso de fallos,
revert, exploración adaptativa); AutoDesign identifica la meta-optimización del
harness con feedback del rollout. En ReaWeb esos patrones se convierten en
**reglas explícitas del harness** (principios 3, 4, 5, 6 de `system_base.txt`) y
en **mecanismos codificados** (`audit_page`, árbol de hipótesis, presupuesto,
`blend_visual_total`). Este ciclo —observación del paper → patrón → regla en
`domain/`— es el mismo que el agente debe reproducir en cada run (ver
`EVOLUTION.md`).