# Punto 12 — Graph Engineering: genealogía, causalidad y grafo de dependencias

**Referencia:** Feng, Y., Xiang, Z., Yang, C., Ma, Q., Chen, Z., et al. (2026).
*Graph Engineering in the Era of LLM Agents: From Individual Intelligence to
System Intelligence*. Survey, 63 págs.
https://github.com/DEEP-JLU/Awesome-Graph-Engineering

## 1. Qué toma del estudio y qué descarta

El paper propone pasar de la *Inteligencia Individual* (un agente con harness y
loop) a la *Inteligencia de Sistemas* (múltiples agentes coordinados mediante
tres grafos: organización de tareas, coordinación de agentes y estado de
ejecución). ReaWeb es un arnés de agente único: la capa multi-agente del paper
(topologías de equipo, routing de capacidades, sistemas operativos de grafos,
ontología formal OWL) **no aplica** a esta escala y se descarta explícitamente.

Lo que sí aplica son tres primitivas estructurales que el paper documenta como
independientes del número de agentes, extraídas de sus secciones §3.3 (Skill
Composition), §4.4.2 (Fault Localization) y §4.5 (System Evolution):

| Primitiva del paper | Fuente en el paper | Adaptación en ReaWeb |
|---|---|---|
| Graph of Skills / SkillDAG | §3.3, §5.1 | `domain/generated/skill_deps.yaml` + `tools/domain/skill_graph.py` |
| Who&When / MAST (fault attribution) | §4.4.2 | Columna `root_cause` en dos granularidades |
| Evolución como grafo versionado | §4.5, EvoFlow | Columna `parent_id` + CTE de genealogía |

## 2. Idea 1 — Grafo de dependencias de capacidades (SkillGraph)

**En el paper:** "Graph of Skills" (Li et al., 2026) representa dependencias y
relaciones de workflow entre skills para recuperar paquetes ejecutables en vez
de entradas aisladas; SkillDAG deja que las relaciones tipadas evolucionen con
evidencia de ejecución.

**Adaptación:** en ReaWeb las capacidades ejecutables son las tools del harness.
El grafo es declarativo (`skill_deps.yaml`, editable vía meta-evolución) y el
motor (`skill_graph.py`) deriva advertencias dinámicas inyectadas en el estado
del agente:

```yaml
audit_page:
  depends_on: [generate_candidate]   # prerequisito duro
audit_visual:
  depends_on: [generate_candidate]
  repeat_guard: true                  # no criticar sin mutación intermedia
```

Tres tipos de arista:

- **`depends_on`** — B sin A previo produce señal inválida (p. ej.
  `select_final` sin `audit_page`; `fetch_repo_topics` sin `fetch_readme`).
- **`inhibits`** — capacidades que compiten por la misma señal. Hoy **sin
  aristas activas**: los críticos VLM visual/creativo se hicieron deliberadamente
  complementarios en el Punto 11. El esquema lo soporta por si la evolución del
  harness introduce solapamientos.
- **`repeat_guard`** — repetir un crítico VLM sin `generate_candidate`
  intermedio repite el mismo juicio sobre el mismo candidato; tras eliminar la
  caché de visión (F1 del Punto 11), cada llamada redundante cuesta tokens
  reales.

La violación se detecta sobre la secuencia real de tools ejecutadas en la run y
aparece en el estado como bloque "🕸 Grafo de dependencias" con las aristas
rotas antes de que el agente gaste otro turno.

## 3. Idea 2 — Atribución causal de fallos (Who&When)

**En el paper:** Who&When (Zhang et al., 2025) atribuye fallos al agente Y al
paso causante, no al síntoma visible; MAST (Cemri et al., 2025) clasifica fallos
en diseño del sistema / coordinación / verificación. El principio: registrar
actores, transiciones y evidencia suficiente para formular hipótesis causales
testeables ("las dependencias estrechan la búsqueda de una causa, no la prueban").

**Adaptación a dos granularidades** (ReaWeb tiene dos niveles donde algo falla):

1. **Nivel run** (`tools/domain/evaluator.py::detect_root_cause`): cuando un
   candidato puntúa mal, el eje más débil bajo el umbral (70) se mapea a un enum
   cerrado — `visual_alignment`, `creative_stale`, `functional_broken`,
   `structure_missing`, `task_mismatch`, etc. La causa viaja en las métricas del
   nodo del árbol y el estado la muestra junto a los `fails`: *"Causa dominante
   (Who&When): visual_alignment — ataca la raíz, no el síntoma"*.

2. **Nivel gate** (`scripts/gate_harness_edit.py`): cuando el acceptance gate
   rechaza una meta-edición, clasifica el rechazo como `unmeasurable`,
   `no_improvement` o `dev_degradation` y lo persiste en `harness_edits.root_cause`.
   `rejected_causes_summary()` agrega los rechazos por causa, convirtiendo el
   historial del gate en evidencia acumulable de qué tipo de edición falla.

## 4. Idea 3 — Genealogía de meta-ediciones (EvoFlow)

**En el paper:** la evolución del sistema debe ser gobernable mediante
procedencia, versionado, validación, replay y rollback (§5.2); EvoFlow y afines
evolucionan workflows como población con ascendencia trazable. Sin árbol
genealógico, cada regla nueva es un punto aislado: imposible saber qué líneas
de mutación producen valor y cuáles solo generan ruido.

**Adaptación:** `harness_edits.parent_id` enlaza cada propuesta con la última
edición **aceptada** del mismo fichero (ancestro de contenido real; los rechazos
no alteran el contenido, luego no son ancestros). `EditSkill` resuelve el padre
en el momento de proponer; la CTE recursiva `edit_genealogy(id)` devuelve la
cadena raíz→hoja. Con esto se pueden podar líneas que mutan sin mejorar nunca y
hacer rollback informado sin perder descendencia válida.

## 5. Esquema DB resultante (`harness_edits`)

```sql
parent_id  TEXT   -- id de la última edición aceptada del fichero (NULL = raíz)
root_cause TEXT   -- gate: unmeasurable|no_improvement|dev_degradation
```

Migración idempotente en `MemoryDB._migrate_harness_edits_graph()`; las bases
preexistentes ganan las columnas al primer arranque.

## 6. Límites (honestidad de adaptación)

- **Sin multi-agente**: las tres capas del paper se reducen aquí a grafo de
  tools, causalidad de evaluador/gate y linaje de ediciones. No hay topología de
  equipo que evolucionar.
- **`inhibits` vacío**: el estudio usa aristas de competencia entre skills
  solapadas; nuestros críticos son complementarios por diseño. Si la
  meta-evolución añade una tercera crítica solapada, la arista procede.
- **Causalidad observacional**: igual que advierte el paper, `root_cause` marca
  correlación (peor eje bajo umbral), no causalidad probada. La prueba llega del
  acceptance gate (¿la edición que ataca esa causa mejora train/dev?).
- La genealogía es lineal por fichero (un padre = última aceptada); no hay
  branching de propuestas concurrentes porque el gate procesa las pendientes en
  serie.
