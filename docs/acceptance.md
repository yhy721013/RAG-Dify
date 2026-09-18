# 分阶段验收记录

目标范围：指南阶段 A～C。当前根目录即指南中的 `mechanical-safety-rag/`。
所有终端命令使用 PowerShell 7；测试使用 `D:\RAG-Dify\.venv`。

## 阶段 A — 已通过模拟验收（2026-09-18）

- 命令：`.\.venv\Scripts\uv.exe run pytest`
- 实际结果：20 passed；2 条上游 TestClient 弃用警告；未访问真实模型或知识库。
- 四个接口、Pydantic 严格契约、五张业务表、schema_version=1、WAL 与短事务已实现。
- 已验证：固定模拟证据生成报告、原文与哈希回填、虚构／跨上下文／跨检查项引用拒绝、观察越界、无命中保留、不完整证据拒绝确定风险、技术故障、鉴权、真实模式禁用 fixture、幂等冲突、报告重启查询、并行隔离和 Markdown 转义。
- 报告始终 `pending_review`；测试通过不等于真实安全评估或模型提示注入测试通过。

## 阶段 B — 真实解析与整理已验证，待人工复核

- 已清点 `test_files` 8 个 PDF，共 218 页。文本层存在：0/3/4/7；无原生文本：1/2/5/6。
- SHA-256、逐页文本计数见本地 `data/manifests/pdf_inventory.json`；未复核标准适用性。
- MinerU 4.0.2 已安装到 `.venv-mineru`，`mineru version --json` 和 `mineru-kit parse --help` 已实测。
- 进入发布前必须完成真实解析产物核对及人工批准；机器解析不能自动批准。

实际解析命令（源文件归档为 sample_0/4/6.pdf）：

```powershell
.\.venv-mineru\Scripts\mineru-kit.exe parse data/raw_pdf/sample_6.pdf -o data/mineru_output/sample_6.zip --format zip --tier standard
.\.venv-mineru\Scripts\mineru-kit.exe parse data/raw_pdf/sample_0.pdf -o data/mineru_output/sample_0.zip --format zip --tier flash --ocr-mode txt
.\.venv-mineru\Scripts\mineru-kit.exe parse data/raw_pdf/sample_4.pdf -o data/mineru_output/sample_4.zip --format zip --tier flash --ocr-mode txt
.\.venv\Scripts\uv.exe run python -m app.cli build-clauses --input data/mineru_output --output data/reviewed/candidates.jsonl
.\.venv\Scripts\uv.exe run pytest
```

结果：3 份／80 页全覆盖，312 条待复核候选；37 passed。所有候选均为 pending、evidence_complete=false。

| 样本 | 页数 | 候选 | 跨页候选 | 图表资产引用 | 未知边界 | 缺失资产 |
|---|---:|---:|---:|---:|---:|---:|
| test_files/0 | 34 | 109 | 12 | 21 | 1 | 0 |
| test_files/4 | 36 | 113 | 16 | 22 | 1 | 0 |
| test_files/6 | 10 | 90 | 3 | 12 | 1 | 0 |

- PDF、完整 ZIP、展开目录、normalized.json、逐页覆盖记录均留在被忽略的 data/。
- sample_6 的 PDF 零基页 3 是空白页，实际输出省略 blocks；已对照页图确认空白并增加回归测试。不会因最后一个文本页存在就认定完整覆盖。
- 已抽看文本页、扫描图页和表格页；这只是软件解析检查，**未执行专业条款原文与适用性人工复核**。
- 首次真实 build 因空白页省略 blocks 失败，修复后成功；结果包含未知边界、跨页和图表复核标记。
- import-reviewed 的原文／PDF／资产哈希、审批记录、上下文依赖和不可变快照门禁已实现；未导入业务批准快照。

## 阶段 C — 离线实现与模拟测试通过，真实联调未验收

- 当前未提供 Dify Service API、知识库密钥、dataset ID 和嵌入模型；未检测到 Docker CLI。
- 已完成离线可验证的同步、映射与评测，不把模拟结果记作真实联调。
- 真实成功请求、脱敏响应、索引完成、分页回读、一一映射、重跑不重复和真实检索缺一不可。

- 已实现 sync-dify、evaluate-retrieval、activate-snapshot，第三方请求集中在 app/dify_client.py。
- 已核查 1.17.1 Service API 源码：单数 document/create-by-text、documents/{batch}/indexing-status、分块分页、records[].segment 与 Workflow result[].metadata 的差别。
- 模拟测试覆盖创建超时后有／无远端文档的对账、重复同步只创建一次、分页、索引失败／超时、漏块／并块／尾块／重复块／文本变化、检索技术失败、条款级评测及激活门禁。
- 实际命令：`.\.venv\Scripts\uv.exe run pytest` → **63 passed in 2.35s**，2 条第三方弃用警告。
- 实际命令：`.\.venv\Scripts\uv.exe run python -m app.cli sync-dify --snapshot pilot_20260918_01` → 退出码 1，`configuration_error: DIFY_KNOWLEDGE_BASE_URL` 未配置。这是预期阻塞，未访问任何真实 Dify 知识库。
- 真实成功请求与响应尚未取得；按指南“缺外部依赖仍继续离线工作”完成了暂定适配和明确标记的合成测试，**不能视为已满足指南先采真实响应再确认契约的现场验收要求**。
- 未运行真实嵌入或检索，未发布业务知识快照，未配置设备类别／检查清单，未实施阶段 D/E。

## 继续推进所需材料

1. 在本地 .env 配置 Dify Service API 地址、Knowledge API 密钥、专用 dataset ID，并确认中文嵌入模型可用。
2. 专业人员对候选条款完成原文、边界、图表、必要上下文与版本适用性复核，生成 approved.jsonl。
3. 根据批准条款提供至少一组真实检索标注，先完成单标准试点，再扩展新的不可变快照。

完整操作顺序见 docs/runbook.md。当前没有将任何真实标准自动标记 approved；data/app.db 中不存在业务条款或报告。

## 补充验证

- 使用 `.venv\Scripts\python.exe` 启动真实 Uvicorn 子进程，在随机本地端口完成四个 HTTP 接口的合成数据闭环并确认匿名查询返回 401；随后停止子进程。运行日志见本地 data/manifests/uvicorn-smoke.log。
- 该 HTTP 冒烟单独使用合成数据库，不污染业务 app.db；示例导出为 data/reports/synthetic-demo.md 和 .json，全部明确为测试内容。
- 312 条真实候选全部通过 ClauseRecord Schema 校验；对 candidates.jsonl 执行 import-reviewed 被 review_required 正确拒绝。
- Compose YAML 仅通过结构检查；没有构建容器或执行 Dify HTTP 节点联通测试。

## 继续执行复查（2026-09-18）

- 配置复查：DIFY_KNOWLEDGE_BASE_URL、DIFY_KNOWLEDGE_API_KEY、DIFY_DATASET_ID 仍未配置；approved.jsonl 不存在；检索标注文件仍为空。
- 先新增回归测试，复现 CRLF 标识行误拒绝，以及混合文档中空白／仅图片链接条款被静默遗漏，共 3 个失败用例。
- 最小修复：先统一换行再识别分块标识，仍保存实际返回文本的哈希；逐条款拒绝去除图片链接后为空的索引文本。
- 修复后全量 63 项通过；阶段 C 的真实创建、索引、重复导入、检索及发布验收仍未完成。
