# Build context is the repo root - see atc-core/Dockerfile's comment for why.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --package history-seeder --no-dev --frozen

# One-shot job, not a server - runs to completion and exits. See
# docker-compose.yml's history-seeder entry: profile "seed", invoked
# explicitly (`docker compose --profile seed run history-seeder`), not part
# of default `up`.
CMD ["uv", "run", "--package", "history-seeder", "python", "-m", "history_seeder.main"]
