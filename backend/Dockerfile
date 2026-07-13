FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv venv && uv pip install .

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV ENV_FILE=/dev/null

# --host :: → dual-stack, required for Railway private networking (IPv6)
CMD ["sh", "-c", "alembic upgrade head && python -m app.initial_data && fastapi run --workers 4 --host :: --port ${PORT:-8000}"]
