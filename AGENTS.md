# AGENTS.md — reaweb-harness

Operativa para agentes que trabajan este repo. Contexto completo metodológico
y de validación A/B en `Docs/PG_AB_VALIDATION.md`.

## Tarea en curso (estado 2026-10-10)

Validación A/B del diseño de prompts del Portfolio Generator (on=PG vs off
=baseline), n=6+6 (REPS=6), con **integridad auditable**:
`valid`, `resolved_models`, `flags.pg_enabled`, permutación exacta 2-colas
sobre C(12,6)=924 + mean/sd + BF10 (JZS). Modelos libres hacen que la batería
sea **multi-día**: cada tanda completa debe ser baseline independiente y no se
comparan tandas con hash/ID del harness distinto.

### Batería decisiva pendiente (modelo capaz): estado PAUSADA por cuota

- OBJETIVO: completar `runs/battery_results_flashpreview/` (12 runs,
  `gemini-3-flash-preview` + juez VLM `groq`). Queda pausada en 2/12.
- RESUME (idempotente, sin riesgo): `bash scripts/battery_resume.sh`
  - Reintenta markers con error (fix 37f7a45); saltos en markers válidos.
  - exit 0 = completa; exit 3 = cuota del día agotada (ventana ~24h rodante);
    reintentar el próximo ciclo (día siguiente o cuando se encienda WSL).
  - `REPS=4` acorta a 8 runs si se prioriza cerrar antes.
- CONSTRAINTS DE CUOTA (medidos 2026-10-10):
  - `gemini-3.1-pro` = limit 0 (permanente) → no sirve.
  - `gemini-3-flash-preview` = 20 `generate_content_free_tier_requests`/día →
    ~2 runs por ciclo; un ping de 1 token consume 1 request: NO hacer pings
    innecesarios; la ventana se agota en minutos.
  - `gemini-3.1-flash-lite` = cupo diario propio (ya entregó la Tanda 4).
  - Groq = inservible como AGENTE (413 con prompts reales, pese a 128k), OK
    como JUEZ VLM (`qwen/qwen3.8-27b`). Nunca driver LLM de batería.
- PREFLIGHT NO gasta cuota (valida firma/config). Para sondear cuota de verdad
  usa 1 solo ping mínimo, y solo si es imprescindible.

### Tandas ya entregadas (baselines independientes, n=6+6, válidas)

- Tanda 4 (flash-lite+qwen/Groq, best): delta on−off **+3.00**, permutación
  **p=0.2511**, BF01≈3.7 → sin efecto detectable.
- Tanda Mistral (openrouter): delta **−0.83**, **p=0.93** → sin efecto.

Con dos baselines nulos libres de baja masa, la hipótesis pendiente de refutar
es "ha de alcanzar masa capaz" → la batería flash-preview. Si converge en nulo,
valorar cambiar de arquetipo (p. ej. `saas-dashboard` con más superficie
funcional) antes que subir n indefinidamente con modelos free.

## Convenciones

- Comandos de tests: `.venv/bin/python -m pytest test/<suite> -q`; suites
  afectadas por cambios de driver: `test_run_battery_robustness.py`,
  `test_run_verifier.py`, `test_llm_resilience.py`, `test_run_interrupt.py`.
- NEVER tocar/quemar claves: solo en `.env` (gitignored). No hacer pings de
  diagnóstico que quemen cuota sin necesidad.
- Todo análisis de batería: `valid`, `resolved_models`, `flags.pg_enabled`;
  jamás reportar tanda contaminada como válida. `runs/` es gitignored.
- Funciones de curva/best están en `tools/domain/evaluator.py` y el utils está
  en `scripts/_common.py`; reportes según convención de `Docs/PG_AB_VALIDATION.md`.