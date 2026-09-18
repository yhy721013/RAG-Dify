# 机械设备安全评估 RAG

依据根目录实施指南推进原型：Dify 原生知识库、MinerU 离线解析、FastAPI 证据服务、SQLite 和 Markdown。阶段A～C已完成，当前按用户授权实施阶段D。
阶段 A 模拟闭环通过；阶段 B 已真实解析 3 份／80 页，首轮 10 条已由用户批准并导入；阶段 C 已在 Dify Cloud 完成这 10 条的真实索引、分页映射、重复同步、检索评测与快照激活。阶段D新增测试后，当前共 96 项测试通过。
本轮范围由用户确认限定为 GB/T 8196-2018 的 10 条：12 道可回答题全部命中，两道多条款题全部找全；3 道无答案题仍返回相似候选，不能据此生成所问数值或要求。
详细命令与结果见 [验收记录](docs/acceptance.md)，操作顺序见 [运行手册](docs/runbook.md)。

阶段D已提供节点代码、结构化Schema和候选生成器；固定观察版本已通过真实Dify检索、HTTPS证据服务与报告保存闭环。完整视觉草稿已恢复并保留鉴权配置，仍待设备类别／清单确认与实拍图片，详见 [工作流规格](workflows/workflow-spec.md)。

在 PowerShell 7 中运行：

```powershell
uv sync --locked
uv run pytest
uv run python -m app.cli init-db
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

本机 uv 位于 `.venv\Scripts\uv.exe`，可用该路径替换上述 `uv`。测试全部在本项目 `.venv` 中执行，不需要真实密钥。

复制 `.env.example` 为 `.env` 并填写真实配置。未配置有效服务密钥、快照和知识库时健康检查返回 `503 not_ready`；所有业务接口需要服务级 Bearer 鉴权。
本机 `.env` 已配置试点 Dify Cloud 知识库，ACTIVE_SNAPSHOT_ID=pilot_20260918_01。其他环境需自行配置连接和密钥；密钥、PDF、解析产物和数据库均不进入 Git。

机器解析产物只生成待复核条款。真实条款必须人工复核，最终报告始终标记 `pending_review`。
