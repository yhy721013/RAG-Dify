# 本地标准复核与设备评估测试台

本入口是用户明确授权的阶段 D 扩展。使用真实 MinerU 和 Dify Cloud；没有离线演示报告。现有 `app.main`、旧 `.env`、阶段 D v3 工作流和五张证据业务表继续兼容。

## Windows 初始化

需要 PowerShell 7、Python 3.12、Git；不需要 Node 前端构建、Redis 或 Docker。首次下载 MinerU 权重需要网络和磁盘空间。解析环境与轻量 API 环境分离。

```powershell
pwsh -File deploy/init-portal.ps1 -InstallMinerU
pwsh -File deploy/doctor-portal.ps1
```

`init` 使用 `uv.lock` 安装工作区 `.venv`；MinerU 使用 `ingestion/mineru-requirements.txt` 安装 `.venv-mineru`。已存在的 `.env.portal` 不覆盖。新配置只生成本机证据服务密钥，不复制开发者的业务凭据。

编辑项目根目录 `.env.portal`。它与旧 `.env` 完全独立。密钥只存放在该本机文件和 Dify Secret，绝不写进前端、DSL 源码或 Git。

| 配置 | 用途 |
|---|---|
| PORTAL_KNOWLEDGE_API_KEY / PORTAL_DATASET_ID | 仅限专用知识库的 Service API 密钥与 ID |
| PORTAL_WORKFLOW_API_KEY | 专用 Workflow 应用的 API 密钥，与知识库密钥不同 |
| PORTAL_EVIDENCE_API_TOKEN | init 生成的服务端 Bearer 密钥，同值绑定 Dify Secret |
| PORTAL_EVIDENCE_PUBLIC_URL | Dify 可访问的证据 HTTPS 地址，只转发到 127.0.0.1:8002 |
| PORTAL_DATA_ROOT | 默认为 data/portal；开发者之间不共享 SQLite 目录 |
| PORTAL_MAX_PDF_BYTES / PORTAL_MAX_PDF_PAGES | 默认为 50 MiB / 300 页，可调 |

## 专用 Dify 环境

每个开发者在自己的 Dify 工作区创建一个空白专用知识库，使用只授权该库的密钥。当前适配器参考 Dify 1.17.1 官方源码；云实例版本由平台控制。若需要使用不同嵌入模型，应同时配置知识库及 Workflow 检索节点并重新真实验收。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.portal.cli configure-empty-dataset
```

该命令只操作空知识库，配置 High Quality、Hybrid Search、语义/关键词各 0.5、Top-5，以及字符串元数据 `rag_snapshot_id`。默认沿用已验证的 Qwen/Qwen3-Embedding-4B 与 SiliconFlow 插件；可用 `--embedding-model`、`--embedding-provider` 指定实际可用模型。

启动本机服务：

```powershell
pwsh -File deploy/start-portal.ps1
```

页面位于 `http://127.0.0.1:8001`，证据服务位于 `http://127.0.0.1:8002`，单独 worker 执行长任务。服务进程与日志在 `data/portal-runtime` 登记。停止脚本会验证 PID 和创建时间，不影响旧 8000 服务：

```powershell
pwsh -File deploy/stop-portal.ps1 -WhatIf
pwsh -File deploy/stop-portal.ps1
```

有运行任务时默认拒绝停止；确需中断可使用 `-Force`，下次启动会标记为已中断，由任务页恢复/对账。普通页面关闭不会中断工作。若操作系统意外终止 worker 且遗留 MinerU 子进程，先在任务管理器核对并停止该任务的解析进程，再恢复解析；每次解析使用独立目录。

管理员为 **8002 证据服务** 配置 HTTPS。Quick Tunnel 可用于临时联调，退出后地址可能变化；重启隧道后同步 `.env.portal` 与 Workflow 的 `EVIDENCE_API_BASE_URL`。不要把 8001 上传/复核页面接到隧道。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m workflows.build_portal
```

将生成的 `data/portal/workflows/portal.candidate.yml` 导入一个**新的** Workflow。保留旧阶段 D 应用。新应用使用 portal-v1、输入 `snapshot_id` 和原生检索节点的手动等值元数据过滤。

无环境绑定的结构模板另见 `workflows/portal.template.yml`。生成器支持 `--model-provider`、`--model`、`--embedding-provider`、`--embedding-model`；检索节点中的嵌入配置必须与实际知识库一致。

在 Dify 管理页面将 `.env.portal` 中证据密钥保存为 `EVIDENCE_API_TOKEN` Secret；将 HTTPS 绑定 `EVIDENCE_API_BASE_URL`。确认两个视觉节点绑定同一 `start.images`，模型均为 Qwen/Qwen3.5-27B，`enable_thinking=false`。完成发布 API 的设置并**关闭公开 Web App**，然后将该应用自己的 API Key 写入 `.env.portal`。配置变化后重启本机三个进程。产品运行只使用官方 Service API；不会读取控制台 Cookie 或自动操作浏览器。

当前 Cloud UI 发布前不开放访问控制。实测采用先保持 Secret 为空、知识版本未发布，发布后立即关闭 Web App，再绑定 Secret 并发布更新的顺序；每次更新后复查 Web App 停用、后端 API 启用。不要把 Knowledge API Key 填入 Workflow API Key；本轮创建的应用密钥以 `app-` 开头。

首次入库前 `/health` 为 `503 not_ready` 是预期；可以正常解析和复核 PDF。至少发布一个版本后才接受评估。

## 上传、复核和发布

1. 页面上传一份本地国家标准 PDF。校验 PDF 内容、加密、大小、页数并归档 SHA-256；相同文件复用既有任务与复核记录。MinerU 固定 `--pages all --format zip --tier standard --ocr-mode auto`，不自动使用远程解析或其他档位。
2. 等待任务完成后打开“对照复核”。左侧显示原 PDF 的本地逐页预览，支持切页及打开原文件；右侧可编辑标准元数据、条款原文、路径、真实来源块和上下文条款 UID，支持拆分/合并。
3. 填写真实复核人，并逐项确认文本、边界、上下文、图表与范围。机器产物保持待复核；修改已批准文本或其依赖会撤销相关批准。来源资产缺失、页覆盖不完整及未知边界不能直接批准。标准状态与来源由维护人员填写，系统不替代适用性判断。
4. 勾选标准并预览新版本。允许只发布已批准且依赖闭合的子集，页面显示剩余待复核条款数。同标准号/版本会整体替换旧条款集合，须显式确认；其他标准累积保留。
5. 人工填写检索问题 JSON 数组，每项为 `case_id`、`query`、`expected_clause_uids`、`answerable`。至少一项可回答问题，目标 UID 从预览中复制。版本、自检复核人和时间由后端固定。检索 Top-5 命中率至少 0.9 且无技术错误，分块/元数据/映射全部回读一致，才发布。

`rag_snapshot_id` 是强制过滤条件；每一版保留独立文档及映射。同步也核对所有已登记历史分区，发现外来文档、元数据漂移或分块变化会失败，不会自动忽略。旧报告内原文保持不变。首版不自动清理历史版本，较多版本会增加索引存储和核验耗时。

未保存的页面编辑会阻止批准；请先保存条款/元数据再确认。已批准内容与当前版本完全一致时，页面及后端阻止重复发布。拆分后需要人工分别设置条款号与来源位置，不能保留重复身份。

## 设备评估与失败恢复

选择 1～4 张同设备 JPEG/PNG，每张 ≤5 MiB，填写工况并确认同设备。后端在提交时固定知识版本；上传图片和执行 Workflow 使用同一个由后端生成的 `user`。SSE 仅在服务端消费，页面轮询有限任务状态。

连接中断后，已取得运行 ID 的任务查询原运行；未取得运行 ID 的已提交请求禁止自动重发，需在 Dify 运行记录核对。失败任务不会展示上一份成功报告。要发起一次新的评估，重新提交新任务；恢复按钮只恢复原任务。

只有 Workflow 成功返回 `report_id`，且通过证据服务 GET 回读、请求/图片/版本/状态与本机持久化一致性检查，页面才展示报告。所有报告 `pending_review`，可以下载 Markdown/JSON，仍需专业复核。

创建文档响应丢失时，同步清单会先按确定性名称对账。存在同名重复或无法确认创建结果时停止；请对照 `data/portal/manifests` 与 Dify 文档列表排查，不直接删除远程数据。`.lock` 文件残留时，先确认没有运行中的发布任务，再按文件记录核查旧进程，手工处理该锁文件。

## 本地验证与交付

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
pwsh -File deploy/export-source.ps1
```

源码包来自 Git HEAD，位于 dist；只包含已跟踪源码、锁文件、无密钥模板和测试夹具。不包含 PDF、解析包、模型权重、数据库、设备照片、报告、虚拟环境或 `.env.portal`。实际通过/未通过项见 `docs/acceptance.md`，不要把 fixture 测试当成真实模型验收。

当前单机、单 worker、可信本地用户设计，没有账号体系或多租户隔离；不要部署为团队公网服务。团队共用、更多设备、知识规模优化和阶段 E 业务准确性评估需要单独设计和验收。

接口依据：[Workflow API](https://docs.dify.ai/en/api-reference/workflow-runs/run-workflow)、[文件上传](https://docs.dify.ai/en/api-reference/files/upload-file)、[元数据字段](https://docs.dify.ai/en/api-reference/metadata/create-metadata-field)、[文档元数据](https://docs.dify.ai/en/api-reference/metadata/update-document-metadata-in-batch)、[固定版本检索契约](https://github.com/langgenius/dify/blob/1.17.1/api/services/entities/knowledge_entities/knowledge_entities.py)。
