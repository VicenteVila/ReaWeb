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
REPS=5 python -m scripts.run_ab_pg_battery          # 10 runs, round-robin on/off
ls runs/battery_results/                            # markers + summary.json
```

Post-análisis (comando mínimo):

```bash
python - <<'EOF'
import json, statistics as st, itertools
from pathlib import Path
rows=[json.loads(f.read_text()) for f in Path("runs/battery_results").glob("*_*_rep*.json")]
on=[r["best"] for r in rows if r["cond"]=="on"]; off=[r["best"] for r in rows if r["cond"]=="off"]
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
| — | Pendiente: re-validación con control real (n≥6, §7) | — |