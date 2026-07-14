# Build context is the REPO ROOT (not this directory) - uv needs every
# workspace member's pyproject.toml present to resolve `{ workspace = true }`
# / relative path dependencies, even when only installing atc-core's deps.
# See docker-compose.yml: each service's `build.context` is `.`.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --package atc-core --no-dev --frozen

ENV ATC_HOST=0.0.0.0
ENV ATC_PORT=8000
EXPOSE 8000

CMD ["uv", "run", "--package", "atc-core", "python", "-m", "atc_core.main"]
