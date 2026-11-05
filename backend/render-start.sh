#!/bin/sh
# Arranque del backend en el entorno de pruebas de Render (ver render.yaml).
# Equivale al CMD del Dockerfile, con 1 worker (el plan gratuito tiene poca
# memoria) y escuchando en IPv4. Va en un script porque Render no interpreta
# las comillas de un `sh -c "..."` escrito en dockerCommand.
set -e
alembic upgrade head
python -m app.initial_data
exec fastapi run --workers 1 --host 0.0.0.0 --port "${PORT:-10000}"
