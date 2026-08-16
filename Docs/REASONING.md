# REASONING — Por qué y cómo se construyó este agente

Este documento recoge el razonamiento completo que llevó a la creación de
**ReaWeb**: el problema de partida, la tesis que lo inspira, las decisiones de
diseño y el historial real de desarrollo. Es documentación para humanos; no se
inyecta en el contexto del agente.

---

## 1. El problema de partida

Los sistemas clásicos de optimización de texto (prompts, programas, workflows de
ML) delegan la *política de búsqueda* en un **controlador externo**: un loop de
evolución, un bandit, o métodos de "gradiente textual" que deciden qué probar,
cuándo parar y cómo combinar candidatos. El LLM solo aporta ediciones locales.

Ese diseño tiene un coste estructural:

- **Fragilidad**: cada dominio requiere un controlador distinto, con heurísticas
  escritas a mano para "qué funciona aquí".
- **Miopía**: el controlador no ve *por qué* un candidato mejora; solo ve un
  número. No distingue un salto real de una casualidad de muestreo.
- **Bajo aprovechamiento del razonamiento**: el LLM sabe diagnosticar y proponer,
  pero se le obliga a ser un mero generador de mutaciones.

## 2. La tesis inspiradora

> "¿Cuánta de esta política de búsqueda puede ser **internalizada** por un único
> agente que usa herramientas?"

Esa es la pregunta del trabajo en el que nos basamos (ver `READAPTATION.md` para
la citación formal). La respuesta del paper es **sí**: un agente con herramientas
de evaluación, análisis, edición y memoria, sin controlador externo, despliega
por sí solo comportamientos de optimizador: verifica ganancias, reutiliza fallos
pasados, revierte ramas improductivas y explora de forma adaptativa bajo
presupuesto.

Nuestra hipótesis de trabajo para **ReaWeb** fue una concreción de esa tesis:

> Si internalizamos la búsqueda en el agente, podemos especializar el *dominio*
> (desarrollo web) sin reescribir el *controlador*, y además hacer que el agente
> mejore su propio harness a partir de lo aprendido en cada run.

## 3. Decisiones de diseño y su porqué

| Decisión | Por qué |
|---|---|
| **Un único loop de agente** (`Agent.run()`) con tools, sin bucle externo | Es el núcleo de ReASearch: la política de búsqueda emerge del razonamiento, no se programa aparte. |
| **Operaciones como tools** (`generate_candidate`, `audit_page`, `edit_skill`, `python_exec`, `fetch_url`, ...) | El paper empaqueta evaluación/análisis/edición/memoria como tools para poder reutilizar el mismo scaffold en dominios distintos. |
| **Evaluador estático ligero** (sin Chrome) en vez de Lighthouse | Coste cero de infraestructura y latencia; suficiente para señalar *tendencias* entre hipótesis. La migración a Core Web Vitals reales queda como mejora futura. |
| **Categoría `task`** (`extract_requirements`) | Evita optimizar el score a costa de la tarea real: si la tarea pide `github.com/VicenteVila/TraceForge`, ese requisito debe aparecer literalmente en el código. |
| **Categoría `structure`** (secciones obligatorias) | Los checks técnicos (skip-link, canvas, sticky) se pueden "rellenar" sin cumplir la tarea. Verificar secciones cierra esa vía. |
| **Proxy `visual` con efectos REALES** (peso 2.0) | Un `canvas` declarado no es diseño moderno; un gradiente en un comentario tampoco. El evaluador exige animación/dibujo dinámico, `@keyframes` usado, `transition` con disparador real, dark mode persistido. |
| **Principio anti-trampa** (`system_base.txt`) | El total es una *señal*, no el objetivo. Un candidato con score alto pero secciones de la tarea ausentes no es válido. |
| **Árbol de hipótesis H0..Hn con parents** | Es la representación de ReASearch de "búsqueda": permite comparar, revertir (`best_branch`/`dead_end`) y razonar sobre toda la historia. |
| **Doble verificación con `audit_page`** | El paper observa que el agente verifica ganancias prometedoras; lo codificamos como tool de confirmación que no duplica nodos. |
| **Memoria persistente en SQLite** (`worked/didnt/try`) | El paper muestra que un esquema simple "qué funcionó / qué no / qué probar" transfiere entre runs; lo guardamos deduplicado por contenido. |
| **Presupuesto con detección de estancamiento** (`BudgetTracker`) | ReASearch "asigna presupuesto y explota/explora"; aquí se traduce en avisos de meseta y parada dura. |
| **Meta-evolución restringida a `domain/`** con validación YAML (`edit_skill`) | Para que el agente mejore sus propias reglas de forma verificable y sin salirse del sandbox del conocimiento. |
| **Snapshot del harness + trend + benchmark** | Añadido por nosotros: necesitábamos *medir* si el harness mejora entre runs (ver `EVOLUTION.md`). |

## 4. Historial real de desarrollo

El razonamiento no fue lineal; fue incremental, con capas de defensa ante
"trampas" observadas y con nuevas herramientas de dominio. Resumen de los hitos
(orden cronológico):

1. **Harness ReASearch base** (`eff0a6b`): el scaffold del agente con tools de
   generación/auditoría/edición, memoria y meta-evolución.
2. **Hipótesis H0..Hn + dashboard visual + categoría `task`** (`8449331`):
   introducimos el árbol de búsqueda y el evaluador con requisitos de tarea.
3. **Eje `visual` en el evaluador** (`5c050aa`): el score de "diseño moderno"
   aparece como dimensión.
4. **Métricas de efectos reales + total ponderado** (`4d9e014`): `visual` pesa
   2.0× y se exige que los efectos sean reales, no menciones.
5. **Memoria en SQLite + limpieza de runs** (`547b888`): de markdown a base de
   datos con `runs`/`lessons`/`experiments`/`tree_nodes`.
6. **Análisis de URLs de referencia** (`cd05c8a`): `fetch_url` para adaptar
   estructura/estética de una web real a la tarea.
7. **Tool `fetch_readme`** (`fd86359`): tarjetas de repos que abren su README
   local en vez de GitHub.
8. **Evaluador anti-trampa** (`71cbfa4`): categoría `structure`, top-level y
   canvas dinámico — cierra las vías de inflar el score.
9. **Grafo de conocimientos** (`4174ae5`, `c2e9177`): arquetipo `knowledge-graph`
   con `fetch_repo_topics` (categorías sujet arXiv por repo) y subnodos animados.
10. **Métricas de evolución** (`d18eb4b`): snapshot del harness por run,
    `task_hash`, delta en experiments, `trend_evolution` y benchmark re-ejecutable.
11. **Empaquetado para GitHub** (`65a05ca`): Docs/ dentro del repo, LICENSE,
    uv.lock, CI, quickstart.

### Lecciones del propio proceso de desarrollo

- El evaluador y las reglas evolucionaron **a contraataque**: cada vez que una
  run "engañaba" al score (canvas muerto, gradientes en comentarios, secciones
  ausentes), añadíamos una verificación más estricta. Esto es meta-evolución en
  tiempo real, igual que la que se pide al agente.
- La **medición de la evolución llegó tarde** (hito 10): las primeras runs no
  tienen snapshot, así que el trend solo puede comparar versiones posteriores.
  Es la decisión que nos llevó a añadir `harness_hash`/`task_hash` para que
  cualquier mejora futura sea cuantificable.
- **Docs/ vs domain/** se separó a propósito: la especificación humana no debe
  ser pisada por la meta-evolución (ver README); re-sincronizar es un paso
  manual consciente.

## 5. Decisiones abiertas (futuro)

- Migrar el evaluador estático a **Lighthouse CI** para Core Web Vitals reales.
- Decidir si `Docs/` debe re-sincronizarse automáticamente desde `domain/`.
- Definir un umbral objetivo para que una lección repetida se convierta en regla
  (hoy depende del criterio del agente; ver `EVOLUTION.md`).