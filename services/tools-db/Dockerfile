# Build context is the repo root - see atc-core/Dockerfile's comment for why.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --package tools-db --no-dev --frozen

ENV ATC_DB_HOST=0.0.0.0
ENV ATC_DB_PORT=9001
EXPOSE 9001

CMD ["uv", "run", "--package", "tools-db", "python", "-m", "tools_db.server"]
