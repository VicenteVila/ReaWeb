# ReaWeb — agente ReASearch de optimización web + meta-evolución.
# Imagen para ejecutar el harness sin configurar el entorno local.
#
# Uso:
#   docker build -t reaweb .
#   docker run --rm -v $PWD/workspace:/app/workspace \
#     -e GEMINI_API_KEY=... reaweb "landing para un SaaS de IA"
#
# (El volumen sobre /app/workspace conserva los candidatos entre ejecuciones.)

FROM python:3.12-slim

WORKDIR /app

# uv: instalador moderno y reproducible
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# dependencias primero (capa de caché)
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

# código
COPY . .

# instalar el proyecto + entry point 'reaweb'
# (editable: config.py resuelve PATHS contra /app, no contra site-packages)
RUN uv sync --no-dev

# Chrome headless para el test funcional (opcional, se degrada sin él)
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/chromium /usr/bin/google-chrome 2>/dev/null || true

ENV GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.1-pro-preview}

ENTRYPOINT ["uv", "run", "reaweb"]