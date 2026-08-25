# Task-CoEvolve en ReaWeb: selección adaptativa de tareas de validación (Punto 10)

> Miyai, A., Aizawa, K., & Yamasaki, T. (2026). *Task-CoEvolve: Efficient
> Harness Optimization via Adaptive Validation Task Selection*. arXiv.
> https://doi.org/10.48550/arXiv.2608.20169

## BibTeX

```bibtex
@article{miyai2026taskcoevolve,
  title   = {{Task-CoEvolve}: Efficient Harness Optimization via Adaptive
             Validation Task Selection},
  author  = {Miyai, Atsuyuki and Aizawa, Kiyoharu and Yamasaki, Toshihiko},
  journal = {arXiv preprint arXiv:2608.20169},
  year    = {2026}
}
```

## 1. Qué propone el paper

La optimización automática de harnesses (Meta-Harness y derivados) evalúa cada
candidato sobre **todo** el set de validación en **cada** iteración. Eso es
caro (tareas long-horizon que ocupan un sandbox decenas de minutos) y estático
(las tareas que todos resuelven o nadie resuelve gastan presupuesto sin dar
señal para rankear candidatos).

Task-CoEvolve **co-evoluciona las tareas de validación con el harness**:

1. **Variance-weighted selection** (Eq. 2 del paper):
   `w_t = max(p̄_t(1−p̄_t), ℓ_t) + λ/√n_t`. La varianza de Bernoulli del
   histórico es máxima cuando los candidatos discrepan (~50 % de éxito) y cero
   cuando la tarea siempre se resuelve o siempre falla: el presupuesto de
   evaluación se concentra cerca de la frontera de capacidad actual. El suelo
   ℓ mantiene vivas las tareas nunca resueltas (pueden desbloquearse al
   mejorar el harness) y λ/√n_t protege a las tareas con pocas observaciones.
2. **Sampling-aware full-set estimation** (Eqs. 3-4): como cada iteración usa
   un subconjunto distinto, los scores crudos no son comparables. Se estima el
   score full-set corrigiendo por la probabilidad de inclusión π_t de cada
   tarea (Horvitz-Thompson), con dos formas:
   - **Hájek** (Eq. 3): `Σ x_t/π_t / Σ 1/π_t` — adecuado si las tasas de éxito
     viven pegadas a 0 o 1 dentro de cada pool.
   - **Diferencia anclada** (Eq. 4): `media(ānclas) + Σ(x_t − āncla_t)/π_t / N`
     — pondera la desviación respecto a un ancla histórico fijo; evita que una
     tarea fácil muestreada rara vez domine la suma (Apéndice A.2 del paper).
   La regla de elección (§3.3) depende de dónde esté la media del pool.

Resultados del paper: en clasificación de texto alcanza el full-set search con
solo el 7 % del presupuesto y lo supera con el 20 %; en Terminal-Bench 2.1
iguala su resultado reduciendo el coste de búsqueda un 67-80 %.

## 2. Mapeo concepto → implementación en ReaWeb

| Concepto del paper | Implementación en ReaWeb |
|---|---|
| Varianza de Bernoulli `p̄_t(1−p̄_t)` | **Varianza muestral del score continuo** (0-100 normalizado a [0,1]): misma propiedad — máxima cuando los candidatos discrepan (`tools/domain/task_coevolve.py::task_weight`) |
| Suelo ℓ_t para tareas nunca resueltas | Suelo ℓ=0.125 para tareas sin historial (n=0): no se excluyen antes de su primera señal |
| Bonus λ/√n_t | λ=0.025, con n≥1 (evita división por 0 en tareas nuevas) |
| Muestreo sin reemplazo ponderado | Efraimidis-Spirakis determinista con seed (`TaskSelector._draw`), m=⌈ρN⌉, mínimo 2 |
| π_t por Monte Carlo | 4.000 repeticiones por defecto (`TASK_COEVOLVE_MC_REPS`) |
| Estimador Hájek (Eq. 3) | `TaskSelector.estimate` con `estimator="hajek"` |
| Diferencia anclada (Eq. 4) | Ancla = media histórica del score por task_hash; tasks sin historia toman la media del pool |
| Regla de elección §3.3 | `choose_estimator`: Hájek si media del pool ≤0.25 o ≥0.75; anclada en zona media (caso típico ReaWeb: scores 78-90) |
| Historial de outcomes durante una búsqueda | **Historial entre runs**: tabla `task_evals` de `memory/memory.db`, indexada por `task_hash`; `runs.best_score` pre-Punto 10 sirve de semilla |
| Selección final Ŝ-max | Leaderboard reporta Ŝ full-suite junto a la media cruda del subconjunto |

Puntos de integración funcionales:

| Lugar | Antes | Ahora |
|---|---|---|
| `scripts/run_benchmark.py --suite` | Siempre las N tareas completas | `--rho X` muestrea ⌈ρN⌉ tareas por varianza y estima Ŝ full-suite; `--full` restaura el comportamiento antiguo. Cada tarea ejecutada queda en `task_evals` |
| `scripts/gate_harness_edit.py` | Train/dev fijas hardcodeadas (el baseline "Naive" del paper: subset fijo → sobreajuste + scores incomparables) | Por defecto elige las 2 tareas más discriminativas del historial (train la mayor varianza, dev segunda con arquetipo distinto); `--fixed-tasks` restaura lo antiguo |

## 3. Qué tomamos del paper, con fidelidad

| Mecanismo | Fiel al paper | Nota |
|---|---|---|
| Pesos ∝ poder discriminante | ✔ | Adaptados a outcome continuo (ver §4) |
| Re-muestreo cada pasada | ✔ | Evita el sobreajuste al subset fijo ("Naive") |
| Corrección por π_t | ✔ | Monte Carlo sobre el mismo procedimiento de muestreo |
| Dos estimadores + regla de elección | ✔ | Hájek disponible aunque el caso ReaWeb caiga casi siempre en anclado |
| Determinismo reproducible | ✔ (+) | Seed explícita (`TASK_COEVOLVE_SEED`), el paper no lo especifica |

## 4. Qué readaptamos al dominio web, y por qué

| Divergencia | Motivo |
|---|---|
| Varianza continua en vez de Bernoulli | El evaluador de ReaWeb produce scores 0-100, no éxitos/fallos binarios. La varianza muestral conserva exactamente la propiedad que el paper aprovecha: vale ~0 cuando todos los candidatos puntúan igual y crece con el desacuerdo |
| Historial entre commits, no dentro de una búsqueda | En ReaWeb el "candidato" es el estado de `domain/` en un momento dado; la serie temporal relevante vive en la DB (una fila por tarea evaluada), agrupada por `task_hash` estable |
| Pool ampliado de 7 → 14 tareas | Con N=7 y ρ=0.5 solo se ahorraría la mitad con alta varianza del estimador; el pool doblado hace significativo el muestreo (`benchmark/tasks.yaml`) |
| ρ por defecto 0.5 (no 0.07-0.20) | Con pools pequeños, subconjuntos de 2-3 tareas dan Ŝ sin señal (paper: Spearman 0.13 a ρ=7 %). ρ=0.5 sobre 14 tareas ≈ el régimen útil del paper |
| Gate de meta-evolución como segundo punto de aplicación | Es donde el paper más valor tendría aquí: el gate era literalmente su baseline "Naive" (subset fijo de 1-2 tareas). La selección adaptativa reduce el riesgo de que el meta-agente sobreajuste a esas tareas |

## 5. Configuración

Variables (env o `.env`, todas con default sensato):

| Variable | Default | Significado |
|---|---|---|
| `TASK_COEVOLVE_ENABLED` | `1` | Activa selección adaptativa en suite y gate |
| `TASK_COEVOLVE_RHO` | `0.5` | Fracción del pool a evaluar por pasada |
| `TASK_COEVOLVE_L` | `0.125` | Suelo ℓ para tareas sin historial |
| `TASK_COEVOLVE_LAMBDA` | `0.025` | Coeficiente del bonus de incertidumbre λ/√n |
| `TASK_COEVOLVE_MC_REPS` | `4000` | Repeticiones Monte Carlo para π_t |
| `TASK_COEVOLVE_SEED` | `13` | Seed del muestreo (reproducibilidad) |

Uso:

```bash
# suite con muestreo adaptativo al 50% (default)
python -m scripts.run_benchmark --suite

# forzar suite completa (y seguir alimentando task_evals)
python -m scripts.run_benchmark --suite --full

# otro presupuesto
python -m scripts.run_benchmark --suite --rho 0.25

# gate con train/dev fijas (comportamiento pre-Punto 10)
python -m scripts.gate_harness_edit --fixed-tasks
```

Tests: `uv run pytest test/test_task_coevolve.py -q` (15 tests, sin API key).
