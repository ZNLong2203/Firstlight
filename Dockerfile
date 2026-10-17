# syntax=docker/dockerfile:1.7
# One image, three processes: `firstlight api|brain|edge` (see compose.yaml).

FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

FROM python:3.12.15-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12.15-slim
RUN useradd --create-home --uid 10001 firstlight
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER firstlight
WORKDIR /home/firstlight
EXPOSE 8000
ENTRYPOINT ["ddtrace-run"]
CMD ["firstlight", "api"]
