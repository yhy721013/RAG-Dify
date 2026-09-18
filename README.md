# 机械设备安全评估 RAG

依据根目录实施指南推进阶段 A～C：Dify 原生知识库、MinerU 离线解析、FastAPI 证据服务、SQLite 和 Markdown。当前进展与外部依赖见 [验收记录](docs/acceptance.md)。

在 PowerShell 7 中运行：

```powershell
uv sync --locked
uv run pytest
uv run python -m app.cli init-db
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

本机 uv 位于 `.venv\Scripts\uv.exe`，可用该路径替换上述 `uv`。测试全部在本项目 `.venv` 中执行，不需要真实密钥。

复制 `.env.example` 为 `.env` 并填写真实配置。未配置有效服务密钥、快照和知识库时健康检查返回 `503 not_ready`；所有业务接口需要服务级 Bearer 鉴权。
本任务生成的本地 `.env` 已随机生成服务密钥；Dify 连接项仍需配置。密钥、PDF、解析产物和数据库均不进入 Git。

机器解析产物只生成待复核条款。真实条款必须人工复核，最终报告始终标记 `pending_review`。
