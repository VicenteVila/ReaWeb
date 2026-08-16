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

### 2.5 Medición de la evolución (cómo se sabe que hubo cambio)

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
  contra los históricos con el mismo `task_hash`.

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