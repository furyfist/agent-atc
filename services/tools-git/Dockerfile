# Build context is the repo root - see atc-core/Dockerfile's comment for why.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --package tools-git --no-dev --frozen

ENV ATC_GIT_HOST=0.0.0.0
ENV ATC_GIT_PORT=9003
EXPOSE 9003

CMD ["uv", "run", "--package", "tools-git", "python", "-m", "tools_git.server"]
