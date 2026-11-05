FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

WORKDIR /app

# Instala las versiones fijadas en uv.lock (las mismas que en desarrollo y
# tests); `uv pip install .` resolvía cada build a las más nuevas.
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV ENV_FILE=/dev/null

# --host :: → dual-stack, required for Railway private networking (IPv6)
CMD ["sh", "-c", "alembic upgrade head && python -m app.initial_data && fastapi run --workers 4 --host :: --port ${PORT:-8000}"]
