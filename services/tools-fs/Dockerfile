# Build context is the repo root - see atc-core/Dockerfile's comment for why.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --package tools-fs --no-dev --frozen

ENV ATC_FS_HOST=0.0.0.0
ENV ATC_FS_PORT=9002
EXPOSE 9002

CMD ["uv", "run", "--package", "tools-fs", "python", "-m", "tools_fs.server"]
