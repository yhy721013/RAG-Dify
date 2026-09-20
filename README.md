# 机械设备安全评估 RAG

依据根目录实施指南推进原型：Dify 原生知识库、MinerU 离线解析、FastAPI 证据服务、SQLite 和 Markdown。阶段A～D的本轮技术验收已完成，尚未开展阶段E业务评测与内部试用。
阶段 A 模拟闭环通过；阶段 B 已真实解析 3 份／80 页，首轮 10 条已由用户批准并导入；阶段 C 已在 Dify Cloud 完成这 10 条的真实索引、分页映射、重复同步、检索评测与快照激活。阶段 D 原基线为 110 项测试；新增本地测试台后的验证记录见下文。
本轮范围由用户确认限定为 GB/T 8196-2018 的 10 条：12 道可回答题全部命中，两道多条款题全部找全；3 道无答案题仍返回相似候选，不能据此生成所问数值或要求。
详细命令与结果见 [验收记录](docs/acceptance.md)，操作顺序见 [运行手册](docs/runbook.md)。

当前stage-d-v3已通过单图、同机双图的真实视觉、6项检索、证据准备、评估模型和报告保存流程，并用真实失败输入验证合法重复引用可继续。正文中的证据ID须已列入该项合法引用数组；未知、未登记及越权引用仍被拒绝。正式 [Dify DSL](workflows/safety-assessment.yml) 与本轮运行配置同步，不含密钥。报告均待专业复核，工作流未发布；模型仍有可见事实误识别，详见 [工作流规格](workflows/workflow-spec.md)。

## 本地标准复核与设备评估页面

本轮用户授权的新入口：上传 PDF → MinerU 完整解析 → 页面人工复核 → 累积知识版本与真实检索门禁 → 图片/工况 → Dify Workflow → 已保存报告。页面为 FastAPI + HTML/原生 JavaScript，无 Node 构建步骤，也没有演示数据运行模式。

```powershell
pwsh -File deploy/init-portal.ps1 -InstallMinerU
pwsh -File deploy/start-portal.ps1
# 打开页面“首次配置与诊断”，按五步向导配置并运行实际检查
```

本机页面：`http://127.0.0.1:8001`。专用证据服务：`127.0.0.1:8002`；数据在 `data/portal`，原阶段 D 试点保持独立。首次使用及失败恢复见 [测试台运行手册](docs/portal-runbook.md)，开发接口见 [Portal API](docs/portal-api.md)，源码交付见 [CONTRIBUTING](CONTRIBUTING.md)。

易用性版本增加配置草稿/空闲应用、实际鉴权与工作流契约诊断、页面管理临时隧道、条款与检索问题表单、图片预览排序，以及可下载的脱敏任务诊断。每位开发者仍需创建自己的专用 Dify 知识库、导入并发布 Workflow；向导明确区分人工确认、只读诊断和真实报告验证。

2026-09-20 实测文本版34页与扫描版10页 PDF 上传和解析、4条/10条两版发布与隔离、真实单图/双图报告，以及混设备拒绝。易用性完善后的本地 `.venv` 共166项测试通过。10条版本的12道可回答题全部命中；3道无答案题仍有相似候选。报告全部待专业复核，这些技术验证不等于安全评估准确率。当前仍只发布 GB/T 8196-2018 的10条，其余候选未入库。

源码、锁文件、无密钥 [Workflow 模板](workflows/portal.template.yml) 及生成器可交付其他开发者；每位开发者配置自己的密钥、模型、知识库和 HTTPS 地址。`deploy/export-source.ps1` 从干净 Git HEAD 导出 ZIP，不包含业务资料、数据库、报告或凭据。本轮不创建或推送远程仓库。

## 原阶段 D 证据服务入口

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
