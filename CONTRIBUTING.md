# Contribuir a ReaWeb

Gracias por querer contribuir. ReaWeb es un harness de investigación
(ReASearch/AutoDesign aplicado al desarrollo web), así que las contribuciones
más valiosas son las que refuerzan la verificación, la medición o la seguridad
de la auto-mejora.

## Configuración

```bash
git clone https://github.com/VicenteVila/ReaWeb
cd ReaWeb
uv sync --extra dev        # uv (recomendado) o `pip install -e ".[dev]"`
cp .env.example .env       # edita GEMINI_API_KEY (opcional para tests)
```

Los tests no requieren API key (móckean LLM y red):

```bash
uv run pytest -q
```

## Cómo contribuir

1. **Haz un fork** y una rama (`feat/...`, `fix/...`, `docs/...`).
2. **Escribe o adapta tests** para tu cambio. El núcleo se prueba con mocks para
   no gastar créditos de API.
3. Ejecuta la suite completa (`uv run pytest -q`) y, si tu cambio toca el
   evaluador o el agente, verifica con una run local barata
   (`uv run reaweb --quick "tarea de prueba"`).
4. Abre un **PR** contra `main` describiendo: problema, solución y cómo se
   verificó. No añadas dependencias nuevas salvo que sean imprescindibles.

## Áreas en las que más se agradece ayuda

- **Verificación**: expandir el evaluador estático (SEO/A11y/perf) y el test
  funcional (Chrome headless).
- **Medición**: métricas de evolución del harness, benchmark y leaderboard.
- **Seguridad**: gates de gobernanza de skills (`skill_auditor`, SAFEEVOLVE) y
  casos adversariales en `benchmark/misevo_tasks.yaml`.
- **Documentación**: `Docs/` describe el *por qué*; `README.md` el *cómo*.

## Convenciones

- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- **Código**: Python 3.10+, sin dependencias pesadas; si añades una, justifícala
  en el PR (el proyecto prioriza coste free-tier y reproducibilidad).
- **Docs/ vs domain/**: `Docs/` es especificación humana; `domain/` es el
  conocimiento que el agente edita en tiempo real. No mezcles ambos en un mismo
  PR salvo que sea deliberado.

## Preguntas

Abre un issue (bug o feature) con la plantilla correspondiente. Para discusión
de diseño, describe el contexto del paper o la observación de una run que
motiva el cambio.