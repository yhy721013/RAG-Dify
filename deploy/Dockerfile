# 与本地已验证 Python 版本对齐；容器构建仍需在有 Docker 的环境验收。
FROM ghcr.io/astral-sh/uv:0.12.16 AS uv
FROM python:3.12.6-slim
COPY --from=uv /uv /bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY app/ ./app/
COPY ingestion/ ./ingestion/
COPY evals/ ./evals/
COPY templates/ ./templates/
COPY config/ ./config/
RUN useradd --uid 10001 --create-home evidence && mkdir /data && chown evidence:evidence /data
USER evidence
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
