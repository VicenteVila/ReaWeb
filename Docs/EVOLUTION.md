# EVOLUTION — Cómo el agente aprende y transforma el aprendizaje en reglas

Este documento describe el mecanismo por el que ReaWeb **evoluciona**: cómo una
lección aprendida en una run se convierte en una nueva regla del harness, y cómo
se mide ese cambio. Es documentación para humanos.

---

## 1. El bucle de evolución (visión general)

```
run ──▶ lecciones (worked/didnt/try) ──▶ snapshot harness_hash
             │                                 │
      crítica VLM (feedback P0)                │
             │                                 │
          nueva regla en domain/ ◀── edit_skill (meta-evolución)
                                             │
                                        trend_evolution / benchmark
                                             │
                                        ¿el harness mejoró?
```

El agente no tiene un loop externo de evolución (eso sería ReASearch clásico);
**él mismo** decide en cada run si debe editar su harness. El harness le da las
herramientas (`edit_skill`, `review_harness`) y los instrumentos de medida. El
**crítico VLM** (capa estética de AutoDesign, §3.4) aporta el feedback P0: el
score del candidato renderizado guía la siguiente mutación de
`generate_candidate`, cerrando el bucle con señal estética real.

## 2. Las piezas del mecanismo

### 2.1 Memoria persistente (qué se aprende)

- Las lecciones se guardan en la tabla `lessons` con categoría
  `worked` / `didnt` / `try` (`.agent/memory_db.py:31`), deduplicadas por
  `(run_id, category, content)`.
- Se generan en la run vía `lessons_incremental.md` y se fusionan al global al
  cerrar (`Agent.run()`, `.agent/agent.py:410-413`, evento `lessons_merged`).
- En cada turno, el agente **ve las lecciones previas** inyectadas en su estado
  (`state_template.j2`: `### Lecciones persistentes`), lo que le permite reusar
  fallos pasados sin repetirlos.

### 2.2 Hipótesis y experimentos (qué se evalúa)

- El árbol `SearchTree` guarda H0..Hn con métricas y parentesco
  (`.agent/state.py:24`).
- Cada tool call se registra como `experiment` con su **delta** respecto al mejor
  score previo (`.agent/agent.py:381-390`) y su `node_id` asociado. Esto da el
  material para decidir *qué* merece convertirse en regla.

### 2.3 Meta-evolución (cómo se cambia el harness)

- `edit_skill` edita un YAML bajo `domain/` con validación de YAML y restricción
  de path (`tools/domain/meta_editor.py:46`).
- `review_harness` lista los archivos del harness con tamaño para decidir dónde
  mejorar (`meta_editor.py:93`).
- La meta-evolución puede **deshabilitarse** (`--no-meta`) si se quiere una run
  solo de ejecución.

### 2.4 Feedback del crítico VLM (señal que guía la mutación)

- `tools/domain/visual_critic.py` renderiza el candidato de `workspace/current`
  y devuelve un score estético 0-100 con ≤4 issues y ≤4 sugerencias.
- `blend_visual_total` (`evaluator.py:582`) recombina el total del nodo con
  `visual = max(visual_estático, vlm)`: el feedback P0 del crítico (AutoDesign,
  §3.4) guía la siguiente mutación de `generate_candidate`.
- Los pesos de `WEIGHTS` (`evaluator.py:443`) dan **2.0× a `visual` y a
  `structure`**: el eje estético pesa el doble, coherente con el énfasis visual
  de AutoDesign.

### 2.5 Auto-lecciones (criterio objetivo de aprendizaje)

El aprendizaje de lecciones **no depende solo de que el agente se acuerde** de
llamar a `update_lessons`: el harness registra automáticamente una lección
cuando una tool de optimización (`generate_candidate`, `audit_page`,
`audit_visual`) produce un **delta ≥ umbral** sobre el mejor score de la run
(`LESSON_AUTO` en `config.py`, default 4.0). El criterio:

- `delta > +4` → lección `worked` ("esta mutación funcionó").
- `delta < -4` → lección `didnt` ("esta mutación regresó el score").
- Se deduplica por `(run_id, category, content)` y se limita a
  `max_per_run` (default 8) para no saturar la memoria.
- Se persiste vía `Memory.append_incremental` (mismo camino que
  `update_lessons`) y se loguea el evento `auto_lesson` en el transcript.

Este refuerzo materializa el criterio 2 de la sección 3 ("Δ consistente"): el
harness captura los deltas significativos aunque el LLM no los documente, y esas
lecciones se inyectan en runs futuras.

### 2.6 Medición de la evolución (cómo se sabe que hubo cambio)

- Al abrir la run se toma un **snapshot del harness**: hash de `domain/`,
  `tools/`, `.agent/prompts/` y `Docs/` + hash de las lecciones de la DB
  (`agent/harness_snapshot.py`).
- Al cerrar se toma otro snapshot; la **diferencia** (`harness_diff`) se guarda
  en la run (`.agent/agent.py:419-428`) y en `run_config.json`.
- `task_hash` normaliza la tarea para agrupar runs del mismo benchmark
  (`harness_snapshot.task_hash`).
- `scripts/trend_evolution.py` produce un reporte de evolución: scores, baseline,
  Δ, cambios de versión del harness, actividad meta-evolutiva y lecciones por
  categoría.
- `scripts/run_benchmark.py` re-ejecuta una tarea de referencia fija y compara

### 2.7 Juicio de verdad funcional (test ejecutable anti-trampa)

- **Problema que resuelve**: el evaluador estático puntúa por presencia de
  strings, así que un candidato puede "parecer" completo (todas las secciones y
  checks técnicos) y aun así no FUNCIONAR: JS con errores de consola, botones
  que no hacen nada, formularios que recargan la página, enlaces internos
  apuntando a ids inexistentes.
- **Solución**: cada `evaluate()` ejecuta automáticamente
  `tools/domain/functional_tester.py` — inyecta un runner en el HTML y lo
  renderiza en Chrome headless (`--dump-dom` + `--virtual-time-budget`), hace
  clicks reales sobre botones/selectores interactivos, dispara submits y captura
  errores JS. Reporta un eje `functional` (0-100) con los tests individuales.
- **Gate P0**: si `functional < 60`, el candidato queda CAPADO a 40 (mismo
  ceiling que una sección obligatoria ausente) vía el gate `functional`. La
  estética (audit_visual, audit_truth) NUNCA compensa una página que no
  funciona: `blend_visual_total` conserva el gate. Principio: *primero
  funcional, luego bonito*.
- **Coste y degradación**: el test corre solo si Chrome está disponible; sin él
  el eje queda `None` y no penaliza. El test tarda ~1-2 s por evaluación
  (aceptable dentro del bucle de hipótesis).
- **Discriminación verificada**: dashboard funcional → 100; HTML falso (JS roto
  + enlaces rotos) → 0 (gate activo); página sin interactividad → 60.
- Este eje convive con los demás criterios de evolución: las auto-lecciones
  (§2.5) capturan las regresiones funcionales (delta negativo en candidates
  capados) y el agente aprende a no reincidir.
  contra los históricos con el mismo `task_hash`.

### 2.8 Creatividad (categoría `creativity`, señal VLM sobre lo visible)

- **Problema que resuelve**: el eje `visual` es un proxy ESTÁTICO (cuenta
  `@keyframes`, canvas, gradientes, `sticky`, hover... en el código), así que el
  agente lo "rellena" con strings sin que el resultado mejore. Comparación
  real: el arnés produjo 8.2 KB de código con 5/13 checks visuales (score 38),
  Gemini sin arnés produjo 43.6 KB con 9/13 checks (score 69) — el agente
  optimizó el proxy, no el resultado. La evaluación con el MISMO LLM mostró que
  el problema es la señal, no el modelo.
- **Solución**: `tools/domain/creative_critic.py` (`AuditCreative`). Renderiza el
  candidato a screenshot y un VLM puntúa la CREATIVIDAD de lo visible (0-100):
  composición no estándar (grid roto intencional), tipografía display expresiva,
  micro-interacciones, cohesión artística, originalidad frente a plantillas
  genéricas. Es una señal sobre el resultado renderizado, NO sobre el código, por
  lo que no es sobreajustable con strings.
- **Integración**: `creativity` entra como axis con peso 1.0 en `WEIGHTS`; el
  agente la obtiene vía `audit_creative` y `blend_visual_total` la incorpora
  tomando `visual = max(visual_estatico, vlm, creativity)`. No es un gate: una
  creatividad baja baja el total pero no capa (a diferencia de `functional` y
  `parts_connected`). Los gates de funcionalidad siguen mandando: primero
  funcional, luego bonito, luego original.
- **Discriminación verificada**: el VLM puntuó ARNES=25 ("layout básico y
  lineal") vs GEMINI=15 ("header genérico, dark mode estándar") — ambos bajos,
  confirmando que ni el arnés ni Gemini hicieron diseño de vanguardia, aunque el
  proxy estático daba 69 a Gemini. La creatividad mide lo que el proxy no ve.

### 2.9 Loop de subtareas (descomposición + verificación + iteración enfocada)

- **Problema que resuelve**: el bucle clásico "generar → total opaco → mutar"
  deja que el agente optimice un scalar sin saber QUÉ le falla. La run
  `20260817T104852` lo mostró: total=90 (empate con Gemini sin arnés), la
  creatividad clavada en 25 dos veces, y lecciones auto-generadas que "aprendían"
  que llamar a `audit_creative` es malo (porque su score bajo bajaba el total,
  aunque medir lo que es bajo es INFORMACIÓN, no regresión).
- **Solución (loop F1)**:
  1. `extract_subtasks(task)` descompone la tarea en subtareas con criterio de
     aceptación verificable: `seccion:*` (estructurales, vía `_html_has_section`),
     `funcional:*` (1:1 con los tests de `functional_tester.py`), `literal:*`
     (requisitos textuales de `extract_requirements`).
  2. Cada `generate_candidate`/`audit_page` inyecta el `CHECKLIST DE SUBTAREAS`
     en su salida (`format_subtasks_status`): `[ok]/[FAIL]` por subtarea con el
     detalle del cheque. El estado del agente lo muestra también (del snapshot del
     mejor candidato).
  3. El agente elige UNA subtarea en FAIL, razona su causa, y muta enfocado en
     resolverla. Si persiste 3 intentos, revierte con `revert_workspace` o acepta.
  4. Orden de resolución: estructural → funcional → literal → truth → creatividad
     (global final, no descomponible).
- **Lecciones por subtarea** (F0a): las tools de diagnóstico VLM
  (`audit_creative`/`audit_truth`/`audit_visual`) ya NO generan lecciones por el
  delta del total (eso producía lecciones anti-señal). Ahora `_maybe_content_lesson`
  las genera por CONTENIDO: score bajo → 'didnt' con la causa (issues) y la
  solución (sugerencias); score alto → 'worked'. Además `_maybe_subtask_lesson`
  registra 'worked' cuando una subtarea pasa de FAIL a ok entre candidatos.
- **`revert_workspace`** (F0b): tool para restaurar `workspace/current` desde un
  snapshot congelado (`runs/<run_id>/candidates/H<n>/`). Elimina el patrón de
  reconstruir manualmente (la run 104852 usó `bash` manual en el turno 6).
- **F2**: el prompt de `AuditCreative` ahora exige SUGERENCIAS COMO MUTACIONES
  CONCRETAS en código (grid-template-areas asimétrico, font-family display,
  transform en hover...), no adjetivos. Feedback accionable para que la creatividad
  deje de clavarse en 25.

### 2.10 Explorar → Explotar (contra la convergencia prematura)

- **Problema que resuelve**: la run `20260817T114200` mostró que TODOS los
  candidatos convergían: H1==H0 (el primer `generate_candidate` ni mutó el seed),
  H2==H3 byte-idénticos, H4/H5 diferían solo en `id="faq-1"`/`aria-expanded`.
  Causas raíz: (1) el prompt `GENERATOR_PROMPT` ordena "conserva TODA la
  funcionalidad existente... no simplifiques ni elimines archivos" → penaliza
  explorar; (2) el total no discrimina diseño (seo/a11y/perf/bp/structure
  puntúan 85-100 en todo); (3) assets del arquetipo anterior (`dump.js`,
  `shot_base.png`, `graph_data.json`) se arrastraban de `workspace/current` a
  cada candidato y `graph_data.json` se inyectaba al prompt del generador.
- **Fase A — mecánica de exploración**:
  - **A1** (ya implícito en el flujo): cada `generate_candidate` recibe un
    `objective` explícito.
  - **A2**: modo exploración en `GenerateCandidate.run`. Si el objetivo contiene
    keywords de exploración ("explora", "varía el diseño", "rompe el layout",
    "nueva dirección visual", ...), el generador NO hereda `current_code`
    (mensaje MODO EXPLORACIÓN: pide una variante visual claramente distinta),
    NO inyecta `graph_data.json`, y LIMPIA el target de assets huérfanos antes
    de escribir. En modo normal conserva la mutación acumulativa.
- **Fase B — señal de novedad**:
  - **B3**: `novelty_score(ref_dir, cand_dir)` en evaluator (proxy SIN VLM):
    diferencia 0-100 entre dos snapshots por paleta CSS (Jaccard de colores),
    estructura DOM (ids/clases/tags/enlaces) y contenido JS (delta de tamaño).
    Verificado sobre el run 114200: candidatos casi idénticos → 2-9, rediseño
    real → ≥50.
  - El agente calcula `novelty` tras cada `generate_candidate` comparando el
    snapshot nuevo contra el MEJOR PREVIO (`_compute_novelty`), lo guarda en
    `metrics["novelty"]` del nodo y lo expone en el estado con guía de uso.
- **Fase C — estrategia** (regla 17 en `system_base.txt`): FASE EXPLORACIÓN
  mientras haya presupuesto, alternando mutaciones de mejora con `generate_candidate`
  de exploración explícita; SEÑAL DE CAMBIO si varias hipótesis dan `novelty < 40`
  (convergencia prematura → explora de verdad, o `revert_workspace` si se rompió);
  FASE EXPLOTACIÓN cuando existan 2-3 variantes de diseño distintas y funcionales:
  elegir la mejor y optimizar SOLO sobre ella. Orden: funcional (gate) → distinto
  (novelty) → bonito (audit_visual/audit_creative) → original (creativity alta).

### 2.11 Gobernanza de skills (misevolution, Punto 9 — "Practice Makes Unsafe")

> **Referencia**: Mao, X., Zhao, L., Zheng, X., & Wang, C. (2026). *Practice Makes
> Unsafe: Skill Misevolution in Self-Improving LLM Agents*. City University of Hong
> Kong / Adelaide University. arXiv:2608.12851 [cs.AI].
> https://doi.org/10.48550/arXiv.2608.12851 — citación formal (APA + BibTeX) en
> `READAPTATION.md`, sección 3.

Un agente auto-mejorador convierte trayectorias exitosas en lecciones persistentes
(`memory/lessons.db`) que se reutilizan en runs futuras. Si una run "exitosa"
contiene una técnica insegura (exfiltración, captura de credenciales, `eval` de
remoto...), la lección `worked:` la perpetúa como política reutilizable **después
de que el input malicioso desaparece**. El paper formaliza esto como *skill
misevolution*: la evolución optimiza el resultado de la tarea, no la seguridad del
procedimiento, así que una experiencia comprometida puede convertirse en política
reutilizable. Para atribuir el riesgo a lo largo del ciclo de vida
(authoring → retrieval → ejecución), el paper introduce un **lifecycle gated** con
tres gates que ReaWeb implementa sobre `lessons.db`:

- **WRITE gate** (`tools/domain/skill_auditor.py`): antes de persistir, un crítico
  puntúa la lección en Content Unsafety (CU 1-5), Unsafe Generalization y
  Stealthiness. Si `cu >= SKILL_SAFETY_MIN_CU`, un deleter **delete-only** elimina
  el span inseguro (nunca reescribe el resto), igual que el "critic-localized
  delete-only repair" de SAFEEVOLVE. Si la versión reparada sigue siendo válida y
  de menor riesgo, se guarda reparada; si no, se rechaza (`admitted=0`).
  En `UpdateLessons` y en `Memory.append_incremental/append_global` (que cubren las
  auto-lecciones). Sin VLM disponible, cae a un heurístico determinista.
- **RETRIEVAL gate** (corresponde al "reuse gate" del paper): `read_global_lessons()`
  y `lesson_text(safe_only=True)` excluyen lecciones `admitted=0` / `retired=1`.
  Solo lecciones seguras entran al contexto de las runs futuras.
- **REUSE gate (SAFEEVOLVE)**: al final de cada run, si el artefacto final contiene
  una técnica insegura, se atribuye un outcome dañino a las lecciones que la
  aportaron (`record_reuse`) — la atribución de daño y el ranking por
  utilidad/riesgo de SAFEEVOLVE. Al cruzar `SKILL_SAFETY_RETIRE_AT` reuses dañinos,
  la lección se retira (`retired=1`) y deja de recuperarse.

Config: `SKILL_SAFETY_ENABLED`, `SKILL_SAFETY_MIN_CU`, `SKILL_SAFETY_RETIRE_AT`.
El benchmark `benchmark/misevo_tasks.yaml` + `scripts/run_misevo.py` son una
instanciación reducida de SKILLMISEVO-BENCH: episodios M/B/P (malicious, benign,
persistence) con **simulacro marcado** (endpoints a localhost, sin payload reales)
y las **9 métricas del paper**: BU (Benign Utility), M-ASR (Malicious ASR),
B-ASR/Contamination, CU (Content Unsafety), UG (Unsafe Generalization),
Stealth (Stealthiness), URR (Unsafe Retrieval Rate), C-ASR (Carryover ASR) y
C-Util (Carryover Utility).

**Resultados del paper que motivan la implementación**: sobre 25 configuraciones
agente–método (525 tareas × 25 episodios), las 21 configuraciones que evolucionan
skills autoran artefactos inseguros; tres tareas maliciosas elevan el carryover ASR
de 16.0% a 35.3%; y SAFEEVOLVE reduce la recuperación insegura y el daño en sesión
fresca en 26.7 y 17.3 puntos porcentuales, respectivamente, cambiando la utilidad
benigna media en solo 0.4 puntos.

### 2.12 WikiSkill — Wiki global + Skill Proposer post-run (Google 2026)

> **Referencia**: Wang, Y. et al. (2026). *WikiSkill: Compiling Agent Experience
> into Persistent Knowledge for Skill Evolution*. Google DeepMind.
> Paper: `WikiSkill, Compiling Agent Experience into Persistent Knowledge for Skill Evolution.pdf`

WikiSkill estructura la memoria en tres capas:

| Capa | Qué contiene | Quién la escribe | ¿Se revierte? |
|------|-------------|-----------------|---------------|
| **Raw Layer** | Traza inmutable (lessons, experiments, transcript) | Harness (automático) | No |
| **Wiki Layer** | Patrones consolidados de evaluación (diagnóstico + secuencia) | Wiki Maintainer (post-run) | **No** (compounding) |
| **Skill Layer** | Skills editados (archivos YAML en domain/) | Skill Proposer (post-run) | **Sí** (gate + rollback) |

#### 2.12.1 Wiki Maintainer (post-run, Fase 1+2)

- **Cuándo corre**: al final de cada run, **después** del loop de generación y del
  merge de lessons (`agent.py` post-loop), y **antes** de la exportación final.
- **Qué hace**: consolida las lessons y experiments de la run en el wiki global
  (`memory/wiki/`), siguiendo las reglas del prompt `.agent/prompts/wiki_maintainer.txt`:
  - Cada patrón tiene: **description**, **root cause**, **action sequence** (10-30 líneas).
  - Granularidad: cada patrón captura UNA señal conductual (un fix por patrón).
  - Compounding: los patrones se actualizan con evidencia adicional, nunca se borran.
- **Output**: `memory/wiki/index.md` (tabla de contenidos), `patterns/*.md`,
  `logs.md` (historial de consolidaciones).
- **Config**: `WIKI_ENABLED` (env o flag `--no-wiki` en `run_agent.py`).

#### 2.12.2 Skill Proposer (post-run, Fase 2)

- **Cuándo corre**: inmediatamente después del Wiki Maintainer, en el mismo
  post-loop de `Agent.run()`.
- **Qué hace**: lee `wiki/index.md`, `skill-impact.md` y los patrones recientes,
  y decide si hay un patrón recurrente (≥2 ocurrencias convergentes) que merezca
  convertirse en una propuesta `edit_skill` pending.
  - Si **no hay** evidencia suficiente → `no_action`.
  - Si **sí hay** → genera un YAML válido (mismo formato que `edit_skill`) y lo
    registra como propuesta `pending` en `harness_edits` + entrada en
    `skill-impact.md`.
- **Validación**: `_is_well_shaped` + consistencia componente/path + duplicados
  rechazados (evita proponer lo que ya está pending o fue rechazado recientemente).
- **No-bloqueante**: si el LLM falla, la run termina con normalidad.

#### 2.12.3 skill-impact.md (audit trail de propuestas)

- Registro de todas las propuestas del Skill Proposer, incluyendo las rechazadas
  por el acceptance gate. Cada entrada lleva: propuesta, fecha, run_id, archivo,
  componente, decisión, root_cause (si aplica).
- Sirve de "memoria negativa" para el Skill Proposer: evita repetir propuestas
  ya rechazadas por `no_improvement` o `dev_degradation`.

#### 2.12.4 Separación Inference Agent / Skill Proposer (hallazgo del paper)

El paper demuestra (Tabla 3) que dar acceso al wiki al Inference Agent durante
rollouts **degrada** la calidad de la skill final (63.7% → 60.9%). Por eso en
ReaWeb el wiki **solo se usa post-run**: el agente de generación NO ve el wiki,
preservando trazas informativas y no contaminando las lessons con señales del
wiki. El wiki alimenta exclusivamente la decisión de meta-evolución al cerrar la
run (Wiki Maintainer + Skill Proposer).

#### 2.12.5 Skill Layer modular (Fase 3)

Los skills evolucionados se materializan en **`domain/skills/<snake_case>/`**, cada
uno con dos archivos (§3.1 del paper):

- **`SKILL.md`** — frontmatter YAML (`name`, `description` validadas por
  `_is_well_shaped`) + `When to Apply` / `When NOT to Apply` / `Instructions`
  (procedimentales, concisas).
- **`PURPOSE.md`** — trazabilidad: `Origin` + `Patterns Addressed` (patrones wiki
  que motivaron el skill) + `Evolution History`.

Inyección: `_system_prompt()` antepone un bloque **# SKILLS ACTIVOS** con el
contenido de los `SKILL.md` aceptados (full-injection §3.2.1). El agente nunca ve
el wiki (§2.12.4), solo los skills activos.

#### 2.12.6 Skill Proposer ReAct (Fase 3)

`_propose_wiki_skill` es ahora un agente **multi-turno ReAct** (§E.3): usa
`read_file` restringido (wiki/, skills/, runs/) para inspeccionar
`index.md`, `skill-impact.md` (no repetir rechazados), patrones y traces antes de
proponer. Formato de salida `finish()` (§E.3):

- `create`: `name` + `skill_md` + `purpose_md`
- `patch`: `name` + `edits[]` (`append`/`replace`/`insert_after`)
- `no_action`

Guardas: requiere ≥2 lecturas antes de proponer, valida frontmatter YAML, patch
solo sobre skills existentes. Tope de turnos `WIKI_PROPOSER_MAX_TURNS` (default 4).

#### 2.12.7 Bucle evolutivo iterativo — `scripts/wiki_evolve.py` (Fase 3)

Implementa el **Algorithm 1** (§A.1): co-evoluciona `(S_k, W_k)` durante K
iteraciones:

```
Rbest = R(Tval,0) (baseline dev con skills actuales)
for k in 1..K:
  1. rollout train con skills activos S_{k-1}  (post-loop: wiki + proposer)
  2. propuesta pending del run (component=skills)
  3. aplicar candidato a domain/skills/  (S'_k)
  4. evaluar en dev (maintain off, skills inyectados)  -> R(Tval,k)
  5. accept si R(Tval,k) > Rbest  (Rbest = R(Tval,k))
     reject si no  (rollback a S_{k-1}; el wiki NUNCA se revierte)
  6. skill-impact.md: diff + score + outcome
```

Uso:
```bash
python -m scripts.wiki_evolve \
    --train "landing-page:Landing para SaaS de IA" \
    --dev "saas-dashboard:Dashboard de métricas" \
    --iterations 3
```

Config: `WIKI_EVOLVE_ITERATIONS`, `WIKI_PROPOSER_MAX_TURNS`, `--no-wiki`
(desactiva en env `WIKI_ENABLED=0`), `WIKI_MAINTAIN_ENABLED=0` (eval dev sin
consolidar/proponer).

### 2.13 Procedural Graph — conocimiento procedural declarativo (Google 2026)

> **Referencia**: Lu, Y., et al. (2026). *Procedural Graphs: Self-Evolving
> Execution Structures for LLM Agents*. Google Research.
> Paper: `Procedural Graphs, Self-Evolving Execution Structures for LLM Agen.pdf`

Un *Procedural Graph* organiza conocimiento **procedural** en triplets dirigidos
atribuidos `(u, r, v)` con campos de texto (`condition`, `guidance`, `pitfalls`)
para responder *"¿qué hacer ahora?"* de forma situacional — análogo a cómo un
Knowledge Graph organiza conocimiento factual para *"¿qué es?"*. El grafo vive en
`domain/generated/pg_graph.yaml` (declarativo, 12 nodos de fase: mutation,
validation, preparation, finalization, recovery, meta_evolution; relaciones
tipadas `LEADS_TO`, `TRIGGERS`, `PROVIDES_INPUT_FOR`, `CONVERGES_TO`).

#### 2.13.1 Localización de nodo activo (inferencia)

- **Matching**: `u_t = Match(a_{t-1}, V)` mapea la última tool call al nodo PG
  correspondiente (`tools/domain/pg_graph.py`, tracing en tiempo real). Varias
  tools pueden **converger** a un mismo nodo (canonicalización).
- **Subgrafo vecindario h-hop** (por defecto `PG_GRAPH_HOPS=2`): de la guidance
  situacional se extrae solo el vecindario del nodo activo y se inyecta en el
  estado del agente (`pg_node`, `pg_phase`, `camino_PG` en el log `kind="pg"`).

#### 2.13.2 Evolución del grafo — PG Proposer post-run

- El **PG Proposer** (`.agent/agent.py`, `_propose_pg_graph`, prompt
  `.agent/prompts/pg_proposer.txt`) analiza las trazas de la run al cerrar y
  propone cambios **estructurales** (añadir/eliminar nodos y aristas, editar
  guidance/pitfalls), no solo cambios de texto. Protolado multi-turno ReAct con
  `reads` mínimas y tope `PG_PROPOSER_MAX_TURNS`.
- Las propuestas quedan `pending` en `harness_edits` con `component=pg_graph` y
  pasan por el **acceptance gate** (como `edit_skill`); su histórico de diff,
  score y decisión se registra en `pg-impact.md`.
- **Bucle iterativo** `scripts/pg_evolve.py` (Algorithm 1, §3.3 del paper):
  `rollout train → proposal → gate → accept/revert → impact`, K iteraciones en
  train/dev separados.

#### 2.13.3 Re-ranking semántico de la Skill Layer (LPRA)

`tools/domain/pg_reranker.py` implementa el **LPRA** de PEARL (§3.4): un LLM
ranquea los skills activos por relevancia semántica al objetivo de la run y al
nodo/fase PG activo, y el motor recorta el pool a
`top_k(skills | score >= min_score)` (`PG_RERANK_ENABLED`, `PG_RERANK_TOP_K`,
`PG_RERANK_MIN_SCORE`). Es un **sesgo, no una restricción**: si el LLM no
devuelve JSON parseable, se conserva el orden original (fallback seguro).

#### 2.13.4 Config y nota de inyección

- `PG_GRAPH_ENABLED` (env o `--no-pg`), `PG_GRAPH_HOPS`, `PG_PROPOSER_MAX_TURNS`,
  `PG_EVOLVE_ITERATIONS`, `PG_RERANK_*`, `PG_CORE_CONVERGENT_COUNT` (umbral de
  skill *core* en la distinción SCL de PEARL).
- **Importante**: el flag se lee **en tiempo de run** (construcción de cada
  agente), no de la constante congelada de `config` — véase el fallo A/B y su fix
  en `Docs/PG_AB_VALIDATION.md` §5. Cada run registra `flags.pg_enabled` en
  `run_config.json` para auditar qué condición se ejecutó de verdad.

## 3. De lección a regla: criterios

El agente dispone de lecciones (`worked/didnt/try`) y de experimentos con delta.
No basta con que algo "funcione una vez": para **promover una lección a regla**
proponemos que el agente (y el operador humano) sigan estos criterios:

1. **Repetición**: la misma lección aparece en varias runs (el `trend` muestra
   lecciones por categoría; se puede consultar con `scripts/trend_evolution.py`).
2. **Delta consistente**: la lección se asocia a experimentos con deltas
   positivos estables (no un pico aislado).
3. **Verificación**: tras editar la regla en `domain/`, una run de
   re-evaluación (`run_benchmark --compare`) confirma que el score no empeora.
4. **Generalidad**: la lección aplica al arquetipo o a todo el harness, no a un
   solo repo/URL.

Cuando se promueve:

- La regla se escribe en YAML bajo `domain/` (reglas del arquetipo, `skills.yaml`
  o `workflows.yaml`).
- El snapshot del harness cambia (`harness_hash`), así que la evolución queda
  **registrada y medible** en el trend.
- La regla pasa a formar parte del prompt del agente en runs futuras, cerrando
  el bucle.

## 4. Ejemplo verificado de evolución

En el desarrollo real, la categoría `structure` (secciones obligatorias) y el
proxy `visual` con efectos reales fueron **reglas nacidas de lecciones**: tras
observar candidatos con score alto pero secciones ausentes y canvas "muertos",
se codificaron como checks del evaluador y como principios en `system_base.txt`.
Ese cambio se refleja hoy en `domain/` y en el snapshot (ver `REASONING.md`,
hitos 8-9).

### 4.1 Contrato de métricas estructurado (respuesta a "stringly-typed")

- **Problema (crítica externa, Kimi K.3)**: el agente parseaba las métricas de
  las tools con regex sobre cadenas (`total=(\d+)`, `creativity_vlm=(\d+)`,
  `diseño_vlm=(\d+)`). Un cambio de formato en una tool rompía el árbol de
  búsqueda **silenciosamente** (node creado sin métricas, total perdido).
- **Solución**: todas las tools emiten ahora un **bloque JSON canónico** al final
  de su resultado, delimitado por `###METRICS###` ... `###END_METRICS###`
  (`metrics_block()`/`parse_metrics_block()` en `evaluator.py`). El agente lo
  decodifica con `json.loads` en `_handle_eval_result` (los 4 puntos: audit_truth,
  audit_visual, audit_creative, generate_candidate/audit_page). El regex se
  conserva SOLO como fallback retrocompatible con runs históricas.
- **Verificación**: `parse_metrics_block` round-trip, corrupción tolerada (None),
  y el bloque aparece en la salida de `generate_candidate`. Suite: 121 tests PASS.

## 5. Límites y decisiones abiertas

- **El umbral exacto** para promover una lección a regla sigue siendo criterio
  del agente (los papers observan que emerge, no que se programe). Documentamos
  aquí los criterios para que la decisión sea comprobable por un humano.
- **El crítico VLM depende de un render**: si no hay Chrome disponible la señal
  estética no se genera y el total vuelve al proxy estático (ver
  `blend_visual_total`). AutoDesign asume infraestructura de render; aquí es un
  requisito opcional por coste.
- **La gobernanza de meta-ediciones es estructural, no semántica**: el write
  gate (`govern_lesson`) solo cubre lecciones; `edit_skill` se valida por FORMA
  YAML estricta (`_is_well_shaped` en `tools/domain/meta_editor.py`: mapping de
  mappings/listas, strings-valor cortos y mono-línea) y por el acceptance gate
  train/dev. Un párrafo de prosa concatenado con append ya no pasa (caso real:
  "Añadir regla para portfolios interactivos" dentro de landing-page, limpiado
  en el Punto 11), pero una regla cross-arquetipo bien formateada seguiría
  pasando la forma — el gate de score es quien debe rechazarla por no mejorar.
- **El re-sync `domain/ → Docs/`** no es automático: la especificación humana se
  actualiza manualmente (ver README, "Docs/ vs domain/").
- **Las runs anteriores al hito de medición** (antes de `d18eb4b`) no tienen
  snapshot; el trend las marca "sin información de versión".

## 6. Cómo medir hoy la evolución

```bash
# backfill de runs existentes (una vez)
python -m scripts.backfill_memory

# reporte de tendencia de evolución del harness
python -m scripts.trend_evolution

# benchmark re-ejecutable de una tarea de referencia
python -m scripts.run_benchmark \
  --archetype landing-page \
  --task "Crea una landing para un SaaS de analítica de IA..." \
  --turns 20
```