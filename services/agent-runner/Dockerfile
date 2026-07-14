# Build context is the repo root - see atc-core/Dockerfile's comment for why.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --package agent-runner --no-dev --frozen

CMD ["uv", "run", "--package", "agent-runner", "python", "-m", "agent_runner.main"]
