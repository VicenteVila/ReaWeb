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