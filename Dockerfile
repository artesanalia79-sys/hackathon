# The simulator is a long-lived process with in-memory state, so it needs a host
# that runs a container, not a serverless function. This image works anywhere that
# does: Render, Fly.io, Railway, Koyeb, a VM.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first: they change far less often than the code does.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api ./api
RUN uv sync --frozen --no-dev

# One worker, on purpose. There is exactly one world, and a second worker would be
# a second simulation with its own incidents — the ids from one would 404 on the other.
# The venv's uvicorn directly, not `uv run` — `uv run` re-resolves on every boot,
# which pulls the dev group back in and needs network before the app can start.
ENV PATH="/app/.venv/bin:$PATH" PORT=8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
