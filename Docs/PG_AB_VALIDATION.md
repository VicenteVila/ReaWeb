# Estudio A/B — Validación experimental del Procedural Graph (PG+PEARL)

**Estado:** primera tanda de baterías completada (n=3+3 y n=5+5), pero **inválida
por un bug de inyección del flag experimental** (§5). El toggle quedó corregido
en el arnés; la re-validación con el grupo control *de verdad* desactivado queda
pendiente. Este documento registra el estudio, lo que destapó sobre el propio
arnés y el plan estadístico para una lectura limpia.

---

## 1. Objetivo

Medir si el *Procedural Graph* (PG declarativo + PG Proposer + re-ranking LPRA de
PEARL + Skill Layer de WikiSkill) mejora la calidad de los candidatos web que
genera ReaWeb frente a un **grupo control sin ese mecanismo**, manteniendo todo lo
demás (prompts base, evaluador, presupuesto) idéntico.

- **Tratamiento (cond `on`)**: `PG_GRAPH_ENABLED=1` → el agente recibe el subgrafo
  PG 2-hop y la guidance situacional del nodo activo, y el post-loop de la run
  consolida wiki + ejecuta PG/Skill Proposer.
- **Control (cond `off`)**: `PG_GRAPH_ENABLED=0` → arnés sin PG (ni contexto de
  grafo, ni proposers asociados).

La métrica es el **score normalizado 0–100** del evaluador ReaWeb
(`tools/domain/evaluator.py`), aplicado igual a ambos grupos.

## 2. Hipótesis

- **H0 (nula)**: la distribución de scores `on - off` es simétrica en torno a 0.
- **H1 (adelantada)**: la condición `on` alcanza en media un score *best* mayor.

Decisión con **permutación exacta de etiquetas** (2 colas) y test de
Mann–Whitney U como sensibilidad. Con la varianza observada (sd ≈ 4–5 pt) y n=5
por grupo solo se detectan efectos grandes; ver §7.

## 3. Metodología

### 3.1 Driver `scripts/run_ab_pg_battery.py`

- **Round-robin** por réplica: dentro de cada `rep`, se alterna `on` → `off` para
  emparejar temporalmente las condiciones y mitigar la deriva de la API
  (latencia, throttling, 503s).
- **Markers reanudables**: cada run persiste `runs/battery_results/<arch>_<cond>_rep<n>.json`
  con `{best, baseline, curve, turns, cost, tools, run_id}`. Una batería
  interrumpida se retoma saltando (`[skip]`) lo ya ejecutado.
- **Aislación del estado**: antes de cada run se vacía `workspace/current`
  (con respaldo en `workspace/ws_backup/`) para que H0 nazca del arquetipo y no
  del legado de la run anterior.
- **Auditabilidad**: el agente registra en `runs/<id>/run_config.json` el flag
  `flags.pg_enabled` efectivo de cada run → es posible verificar *a posteriori*
  que el toggle llegó al arnés **sin** gastar una sola llamada LLM más (§5).

```bash
REPS=5 python -m scripts.run_ab_pg_battery          # whole battery (portfolio-creative)
ARCH=saas-dashboard REPS=3 python -m scripts.run_ab_pg_battery
BATTERY_OUT=/tmp/out python -m scripts.run_ab_pg_battery
```

### 3.2 Métricas por run

| Métrica | Definición |
|---|---|
| `baseline` | score de H0 (primera evaluación de la run) |
| `best` | máximo score alcanzado en la curva H0→Hn |
| `curve` | lista `[baseline, ..., best]` (una entrada por hipótesis evaluada) |
| `turns` | presupuesto de turnos consumido |
| `tools` | nº de tool calls emetidas |
| `cost` | coste LLM estimado USD (BudgetTracker) |

## 4. Hallazgos de instrumentación — lo que el estudio destapó

El ejercicio de validación era, en sí, un instrumento: al intentar medir el
efecto, expuso **cuatro defectos silenciosos** del arnés que ninguno de los
scores aislados había revelado. Están corregidos en este commit.

### 4.1 Meseta 66/70 — la caché semántica mataba la diversidad de mutaciones

**Síntoma**: los scores quedaban clavados en un rango estrecho sin importar nada.

**Causa raíz** (medida): la caché LLM con umbral de similitud 0.80 operaba sobre
el **prompt completo** de `generate_candidate`. Como task / sections / reference
son estáticos dentro de una run, prompts con objetivos *distintos* colisionaban
en la caché y devolvían **la misma página generada** repetidamente. Evidencia
empírica: las 6 generaciones de una run tenían **md5 idénticos** (H0/H1/H2
idénticas), `total=40` con 2 archivos y diversidad muerta.

**Fix**: `generate_candidate` usa `llm.generate(..., use_cache=False)`
(`tools/domain/web_generator.py:464`): una mutación es una llamada aleatoria con
objetivo propio y necesita salida fresca. La caché se mantiene para el resto de
llamadas deterministas del arnés (lecciones, auditores de texto, etc.). Verificado
con batería real: tras el fix las generaciones tienen md5 distintos, `total` 67+ y
la baterse del usuario salió del platô. El mismo bypass se aplicó al loop del
agente (`.agent/agent.py:1131`): la caché también re-servía texto de stall e
inducía que el agente emitiera turnos similares y decisia igual ante estados
parecidos — comportamiento de un loop *muerto* que la validación A/B también
estaba "midiendo".

### 4.2 Sub-task funcional permanente en FAIL — el gate estricto no podía cerrar

**Síntoma**: subtareas funcionales nunca terminaban de pasar (p. ej.
`grafo_visible` en un portfolio sin `#knowledge-svg`), atrapando el
`select_final` y disparando `auto_unblock` en vano.

**Fix**: `tools/domain/evaluator.py` `subtasks_status`: un subtask funcional sin
test ejecutado para ese candidato deja de ser `ok=False "test funcional no
ejecutado"` (FAIL **permanente** e irreparable para ese candidato) y pasa a ser
`ok=True "no aplicable (elemento no presente o test no ejecutado)"` — sin
evidencia NO hay infracción, igual que en `evaluate()`.

### 4.3 503 UNAVAILABLE — la batería se rompía a mitad

**Síntoma**: `run_single` abortaba con excepción por `503 UNAVAILABLE / high
demand` de Gemini, dejando la batería a medias y el marker sin escribir.

**Fix**: `.agent/llm.py` `_complete` reintenta cada modelo de la cadena hasta 3
veces con backoff `time.sleep(5 * (attempt+1))` antes de saltar al siguiente
modelo. Los 503 son transitorios; reintentarlos convierte una batería rota en una
lenta.

### 4.4 El flag experimental se congelaba en el import — OFF corrido como ON (fallo crítico)

Ver §5. Es el fallo que invalida las tandas actuales y el que motivó la
auditabilidad por-run.

### 4.5 La cadena de fallback servía otro modelo sin que nadie lo viera (fallo crítico)

`run_config.json` guarda el modelo **pedido**, no el **resuelto**: cuando Pro
volvió a dar `RESOURCE_EXHAUSTED`, la cadena cayó a `gemini-3.1-flash-lite` y las
7 runs "gemini-3.1-pro-preview" de la tanda Gemini se ejecutaron en realidad
con flash-lite. Se detectó por el coste: **$0.018/run cuadra con flash-lite
($0.10/$0.40 por M) y no con Pro ($2.50/$15)** para ~6 turnos con prompts de
~15k tokens.

Consecuencia: esa tanda no es una línea base de Pro (y su consumo real era ~15-25x
menor que con Pro sirviendo). **Corrección**: cada marker registra ahora
`model`/`provider` resueltos y el `summary.json` calcula `resolved_models`,
`failed_runs` y `valid` (`valid=false` si se mezclan modelos o hay runs sin score).
Regla: no analizar una batería sin comprobar `valid` y `resolved_models`.

### 4.6 Cuello de tokens por proveedor: el VLM es barato, el agente no

Medido con capturas reales del harness (viewport 1280x900, el que usan los tres
críticos):

| llamada | tokens | límite del tier | veredicto |
|---|---|---|---|
| VLM (`qwen3.8-27b`, 1 captura) | 1.808 in | 8.000 TPM | viable |
| VLM × 73 (12 runs) | ~134.600 in | — | ~17% del presupuesto |
| Agente (prompt del harness) | ~15.200 in | 8.000 TPM | **413 siempre** |

Groq **cuenta píxeles, no base64**: un PNG de 18,9 KB (base64 ≈ 6,4k "tokens de
texto") solo consume 1.808 tokens. Los tres VLM comparten viewport, luego el coste
y el trato son iguales en ambos brazos. Lo que no cabe en Groq es el agente
(estado + 17 schemas de tools, más el HTML entero en la verificación doble de
`audit_page`), de ahí la separación `LLM_PROVIDER` / `VISION_PROVIDER`.

## 5. El fallo de inyección del flag (fallo crítico) y su corrección

**Diseño del A/B** — el driver alterna la condición por env:

```python
os.environ["PG_GRAPH_ENABLED"] = "1" if cond == "on" else "0"
```

**Bug** — `config.py:108` evalúa `PG_GRAPH_ENABLED = os.environ.get(...)`
**una sola vez, al importar `config`**; el agente la leía con
`from config import PG_GRAPH_ENABLED` (`agent.py:92`) → valor congelado durante
todo el proceso. Como el driver importa el arnés una vez al arrancar, **todas las
runs heredaron el valor del primer import y el grupo `off` corrió con PG activo**.

**Evidencia** (en las 10 runs de la tanda n=5+5):

- Las **10 runs**, ON y OFF, registran eventos `kind="pg"` con
  `pg_node='generate_candidate'`. Solo es posible con `pg_enabled=True`: en OFF
  real `_track_pg` (`agent.py:237`) retorna y deja `pg_node=None`.
- Ninguna run tenía el flag efectivo registrado (ni en marker ni en
  `run_config.json`) → el problema era **invisible a posteriori**.

**Fix aplicado** (`.agent/agent.py`):

```python
self.pg_enabled = os.environ.get("PG_GRAPH_ENABLED", "1") != "0"
self.pg_graph = load_graph() if self.pg_enabled else None
```

El flag se lee **en cada construcción de agente** (una por run) y el grafo solo
se carga si está activo. Además `run_config.json` ahora persiste
`flags.pg_enabled`, de modo que cada run de una batería futura es auditable de
forma trivial (lectura de JSON, sin LLM).

## 6. Resultados

> ⚠️ **Las dos tandas completadas son INVALIDAS** por el fallo de §5: ambos
> grupos corrieron con PG activo. Se listan con carácter de diagnóstico del
> instrumento, no del tratamiento.

### Tanda 1 — n=3+3 (plurality of reps 1–3)

| | on | off |
|---|---|---|
| best | 83, 82, 82 | 77, 85, 77 |
| media (sd) | 82.3 (0.6) | 79.7 (4.6) |

Delta `on-off` = +2.67; permutación exacta 1-cola p=0.20; MC 2-colas p=0.399.

### Tanda 2 — n=5+5

| | on | off |
|---|---|---|
| best | 83, 82, 82, 73, 75 | 77, 85, 77, 78, 75 |
| media (sd) | 79.0 (4.6) | 78.4 (3.8) |

Delta `on-off` = +0.60; permutación exacta 2-colas **p=0.873** (220/252).

**Lectura honesta**: sin efecto distinguible del ruido — como es de esperar
tratando dos grupos *idénticos*. No hay implicación sobre la eficacia de PG.
Nota ambiental: esta tanda se ejecutó con la API de Gemini muy castigada
(503s frecuentes, runs de 16–29 min); el `[skip]`/retomabilidad del driver se
estrenó en esa tanda.

### Tanda 3 — n=6+6 (VÁLIDA, pero con otro modelo: `open-mistral-nemo` + `pixtral-12b`)

Flag auditado run por run (`on` → `pg_enabled=true`, `off` → `false`), sin mezcla
de modelos. Datos en `runs/battery_results_mistral8b/` (12 markers + `summary.json`).

| | on | off |
|---|---|---|
| best | 76, 77, 77, 80, 82, 83 | 75, 77, 77, 81, 82, 85 |
| media (sd) | 79.2 (2.9) | 79.5 (3.8) |

Delta `on-off` = **−0.30**; permutación exacta 2-colas **p=0.9329** (462/924
reasignaciones); 6 turnos y ~11 tools medios en ambos brazos; coste total $5.59.

**Lectura**: con este modelo/juez **no hay efecto detectable** del PG — la
diferencia observada es ruido. No es una replicación de la configuración Gemini
(agente y juez cambian), sino una **línea base independiente**: sus datos no se
pueden sumar ni comparar con las tandas 1–2, solo usar como referencia interna.

### Tanda 4 — n=6+6 (VÁLIDA, `gemini-3.1-flash-lite` + `qwen`/Groq)

Harness ya con **verificador L0** (§4.7) y **modo integridad** (un solo modelo;
el dataset no se puede contaminar por fallback). Ejecución el 2026-10-10: la
cuota free de `gemini-3-flash-preview` está cerrada (`limit: 0` para pro) o
limitada a 20 requests/día, así que se corrió con flash-lite, cuyo cupo diario
estaba operativo. Flag auditado run por run (12/12 OK). Datos en
`runs/battery_results/` (12 markers + `summary.json`, `valid=true`).

| | on | off |
|---|---|---|
| best | 82, 73, 74, 70, 73, 80 | 74, 71, 70, 70, 73, 76 |
| media (sd) | 75.3 (4.6) | 72.3 (2.4) |
| tools (media) | 12.7 | 13.0 |

Delta `on-off` = **+3.00**; permutación exacta 2-colas **p=0.2511** (232/924);
BF01 (JZS, r=√2/2) ≈ 3.7 → la evidencia favorece H0, aunque la dirección es
positiva. Coste total ≈ $0.31; on y off con ~13 tools y coste igual por brazo
(§4.7 invierte presupuesto: el `on` hacía re-rank, pero sin desbalance neto).

**Lectura honesta**: tercera tanda completa VÁLIDA y segunda con diseño limpio
(con verificador): **sin efecto detectable** del PG a n=6+6. El +3 cae dentro
del ruido; además `on` arrancó con baseline peor (62.5 vs 65.0) y terminó con
más varianza. **Línea base independiente** de Mistral y del resto: no sumable.

### 4.7 Verificador de pasos (L0) + preflight (L3)

El harness iteraba sobre un workspace roto sin recuperación automática: si una
mutación dejaba `index.html` inusable (o rompía la funcionalidad previa), la
siguiente mutación se construía encima de la basura y la run quemaba turnos y
cuota. El verificador añade invariantes **100% locales (gratis)** tras cada
`generate_candidate`:

- `index.html` existe, no está vacío, no tiene wrappers/fences, y contiene `<html>`.
- Sin regresión del GATE funcional (si lo previo pasaba el gate y la mutación lo
  suspende → paso roto, se rechaza). Una regresión de *score* NO se rechaza
  (es señal de exploración y ya la trata el árbol).
- Opcional (`VERIFIER_CHECK_RENDER`): la página renderiza en Chrome local, lo que
  además evita lanzar audits VLM (que sí cuestan tokens) sobre páginas rotas.

Si falla, el harness **restaura el workspace desde la última snapshot verificada**
(helper `restore_workspace_from` compartido con `revert_workspace`), retira el
nodo del árbol (memoria + DB, para que `best()` no vuelva a un candidato cuyo
workspace ya no existe), **no** registra lección ni experimento del paso
rechazado, y realimenta al agente para reintentar desde el estado bueno.
Rechazos en cadena: 1 feedback; a `VERIFIER_MAX_REJECT_BEFORE_ESCALATE` (2)
escala una vez con objetivo de reparación (`auto_unblock`); a
`VERIFIER_MAX_REJECT_BEFORE_STOP` (3) la run se detiene **honestamente** con el
último candidato verificado (el driver la marca sin abortar la batería).

`PREFLIGHT=1` ejecuta un sondeo **antes** de comprometer una batería: 1-2
llamadas mínimas que verifican credenciales/cuota, miden el prompt real con
schemas y avisan si el prompt está ≥80% del límite TPM del proveedor (habría
detectado el muro 413 de Groq antes de quemar reintentos), y proyectan el coste
para decidir n=6+6 vs n=4+4.

**Regla de validación**: el verificador se aplica **idéntico en ambos brazos**
(simétrico, sin dependencia de la condición) y modifica el harness → toda
batería lanzada con el verificador activo es un **baseline nuevo**: las tandas
anteriores (Gemini/flash-lite, Mistral) quedan como histórico no comparable.

## 7. Poder estadístico y diseño propuesto

- **n por grupo**: con la varianza observada (sd 4–5 pt), para detectar un delta
  real de 5 pt con poder ~0.8 (α=0.05, 2 colas) hacen falta **n ≈ 6–8** por grupo.
  n=5 solo detecta efectos grandes.
- **Covariables a registrar** en una re-validación: nº de reintentos 503 por run
  (proxy de salud de la API), modelo efectivo usado, timestamp de inicio — y
  verificar SIEMPRE `flags.pg_enabled` de cada run antes de analizar.
- **Diversificación**: existen 7 arquetipos (`domain/archetypes/`). Un arquetipo
  con más superficie funcional (p. ej. `saas-dashboard`) podría discriminar mejor
  el efecto del PG que `portfolio-creative`.

## 8. Reproducibilidad

```bash
cd reaweb-harness
# sondeo previo (1-2 llamadas) para no lanzar una batería contra cuota agotada
PREFLIGHT=1 LLM_PROVIDER=gemini VISION_PROVIDER=groq python -m scripts.run_ab_pg_battery
# solo si PREFLIGHT_OK: el modelo del AGENTE y el del JUICIÓN de imágenes son independientes
# (la batería fuerza AL SOLA modelo y pausa limpia si la cuota muere a mitad)
LLM_PROVIDER=gemini VISION_PROVIDER=groq REPS=6 python -m scripts.run_ab_pg_battery
ls runs/battery_results/                            # markers + summary.json
# si la cuota se agotó: BATTERY_PAUSED → repetir el MISMO comando otro día (skip + resume)
```

Restricciones de cuota medidas el 2026-10-10 (free tier):

- `gemini-3.1-pro-preview`: `limit: 0` requests/día (cerrado, no recargable).
- `gemini-3-flash-preview`: **20 requests/día** (una run ≈ ese cupo) → la batería
  con este modelo se completa en varias tandas diarias (`BATTERY_PAUSED` + resume).
- `gemini-3.1-flash-lite`: cupo diario mayor (operativo incluso con flash agotado).
- Groq **no sirve como agente**: el prompt real turno-1 (≈5.9k tokens) ya devuelve
  `413 Request too large` aunque el modelo declare contexto 131072 — muro estructural.
  Groq sí vale como **juez VLM** (`qwen/qwen3.8-27b`), que es su rol en la batería.

Post-análisis: primero `valid`/`resolved_models` del `summary.json`, y solo
después la comparación (los markers se leen igual):

```bash
python - <<'EOF'
import json, statistics as st
from pathlib import Path
s=json.loads(Path("runs/battery_results/summary.json").read_text())
print("valid:", s["valid"], "| modelos:", s["resolved_models"], "| fallos:", s["failed_runs"])
rows=s["results"]
on=[r["best"] for r in rows if r["cond"]=="on" and r["best"] is not None]
off=[r["best"] for r in rows if r["cond"]=="off" and r["best"] is not None]
print("on ", on, st.mean(on), "| off", off, st.mean(off))
EOF
```

## 9. Historia de la validación (changelog)

| Fecha | Evento | efecto |
|---|---|---|
| — | Batería previa al estudio (n=3, condición mal inyectada) | delta +2.67, no significativo — **descarte** |
| — | Fix caché semántica en generador + loop (§4.1) | la diversidad de mutaciones vuelve; platô estimable abandona |
| — | Fix sub-task FAIL permanente (§4.2) y retry 503 (§4.3) | batería robusta a medias; gate estricto deja de reparar en vano |
| — | Tanda 1 n=3+3 | resultados listados (§6), **inválidos por §5** |
| — | Tanda 2 n=5+5 (reps 4–5) | resultados listados (§6), **inválidos por §5** |
| — | **Fix flag congelado** (§5) + `flags.pg_enabled` en run_config | toggle efectivo + auditabilidad por run |
| 2026-09-30 | Provider OpenAI-compatible genérico (`mistral`, `groq`, `cerebras`, `openrouter`) + `VISION_PROVIDER` | deja de estar atado a Gemini para agente o juez |
| 2026-09-30 | Tanda Gemini de 7 runs: en realidad servida por flash-lite (§4.5) | no es línea base de Pro; el modelo resuelto pasa a auditarse |
| 2026-09-30 | Tanda 3 n=6+6 con `open-mistral-nemo` + `pixtral-12b` | **válida**: delta −0.30, p=0.9329 → sin efecto detectable en este modelo |
| 2026-09-30 | Parser tolerante de `===FILE===` con fences Markdown | salida del modelo ya no se pierde ni ensucia el workspace |
| 2026-09-30 | Límites de tokens separados con/sin tools; run fallida no aborta la batería | batería continua y reanudable ante cuotas agotadas |
| 2026-10-10 | Verificador L0 (§4.7): invariantes locales post-mutación + rollback al último estado verificado + escalada y cierre honesto | el harness deja de iterar sobre un workspace roto y de quemar cuota en pasos inválidos |
| 2026-10-10 | Preflight L3 (§4.7): sondeo de credenciales/cuota y medida del prompt con schemas antes de lanzar | 1-2 llamadas en vez de REPS≈12 contra una cuota agotada; decide n=6+6 vs n=4+4 con proyección |
| 2026-10-10 | Modo integridad de batería: `LLM_SINGLE_MODEL` (cadena sin fallback) y **pausa limpia** por cuota (resumen resumible + exit 3) | la batería no se contamina con modelos mezclados ni gira 1.5 h sobre un 429 sin dejar summary |
| 2026-10-10 | Tanda 4 n=6+6 con `gemini-3.1-flash-lite` + `qwen`/Groq | **válida**: delta +3.00, p=0.2511, BF01≈3.7 → sin efecto detectable; 2ª línea base independiente |
| 2026-10-10 | Fix resume: los markers con error (cuota) se reintentan, no se saltan | una run fallida no se da por hecha al reanudar; el dataset no se envenena |
| 2026-10-10 | `scripts/battery_resume.sh`: catch-up idempotente de la batería (bucle multi-día, exit 0=completa / 3=cuota agotada) | la tanda capaz avanza cada ciclo de cuota sin intervención manual; útil con PC encendido intermitentemente |
| — | Pendiente: re-validación con control real (n≥6, §7) | — |