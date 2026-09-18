# 本地运行与阶段 C 联调手册

## 1. 工程与环境

根目录 `D:\RAG-Dify` 即指南的工程目录，不额外嵌套同名项目。终端使用 PowerShell 7，所有数据文件 UTF-8。

```powershell
Set-Location D:\RAG-Dify
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\uv.exe sync --locked
.\.venv\Scripts\uv.exe run pytest
.\.venv\Scripts\uv.exe run python -m app.cli init-db
```

新机器先安装 Python 3.12 和 uv，再 `uv sync --locked`。API 依赖锁定在 uv.lock；不要安装全局 pytest 代替项目环境。
MinerU 独立环境使用 `uv venv --python 3.12 .venv-mineru` 和 `uv pip install --python .venv-mineru\Scripts\python.exe -r ingestion/mineru-requirements.txt`。该冻结记录来自 Windows；其他平台需重新验证。

## 2. 真实样本与解析

原始文件保持在 test_files，副本在 data/raw_pdf，SHA-256 和原始路径清单在 data/manifests/pdf_inventory.json。
已验证的 sample_0、sample_4 对应同编号样本，具备文本层；sample_6 是扫描件。解析日志记录在 data/manifests。

```powershell
.\.venv-mineru\Scripts\mineru.exe version --json
.\.venv-mineru\Scripts\mineru-kit.exe parse data/raw_pdf/sample_6.pdf -o data/mineru_output/sample_6.zip --format zip --tier standard
.\.venv\Scripts\uv.exe run python -m app.cli build-clauses --input data/mineru_output --output data/reviewed/candidates.jsonl
```

构建器会保留 ZIP 并安全解包。默认用导出目录名匹配 `data/raw_pdf/<目录名>.pdf`；其他命名可在导出目录放 source.json：`{"source_archive_path":"raw_pdf/实际文件.pdf"}`。
不自动下载远程资产，不容许越界 ZIP 路径。normalized.json 保留逐页来源；candidates.manifest.json 记录各文件结果；candidates.md 供核对。
缺页、不完整包、未知结构均不可作为完整标准发布。空白页也有覆盖记录，需核对原 PDF。

## 3. 人工批准与不可变快照

先从一份标准选择试点条款，将 candidates.jsonl 复制为 data/reviewed/approved.jsonl；不要直接把全部候选批量改成 approved。
JSONL 每行一个条款，契约见 config/clause-record.schema.json。逐项核对原文、条件、数字、单位、否定词、跨页、图表及脚注，确认适用范围与状态来源。

- 填写 standard_code、standard_name、edition、scope、standard_status、status_verified_at、status_source。
- 保留 source_file_sha256、source_archive_path、source_page_count、source_spans、asset_refs 和资产哈希；印刷页码不确定就留 null。
- 修正 clause_no 和完整 clause_path；正文和附录的同名编号不能共用身份。
- 确认父条款条件等 context_clause_uids；不能因本条已识别而遗漏必要上下文。
- 填写 reviewed_by、reviewed_at 和 review_notes（说明相对机器文本的修改），逐项解决 review_issues 后清空。
- 设置 boundary_status=confirmed、content_review_status=approved、evidence_complete=true；真实条款 is_test_fixture=false。
- standard_uid、clause_uid、content_sha256 可以留空，由导入器确定性计算；提供值时必须一致。

身份算法在 ingestion/import_reviewed.py：`standard_identity(标准号, 版本)` 和 `clause_identity(standard_uid, 版本, 完整路径)`。需要维护上下文关系时先使用这两个函数计算目标 UID，然后统一导入。

```powershell
.\.venv\Scripts\uv.exe run python -m app.cli import-reviewed --input data/reviewed/approved.jsonl --snapshot pilot_20260918_01
```

导入会核查审批字段、原 PDF 页数与哈希、图表文件与哈希；同一快照相同内容重跑不变，不允许覆盖或追加不同内容。
扩展试点集合时创建新快照和独立 Dify 知识库，例如下一快照编号；旧报告的证据副本不受影响。

## 4. Dify 环境与真实契约采集

在本地 .env 填写 DIFY_KNOWLEDGE_BASE_URL（含实例实际 Service API 前缀，通常 /v1）、DIFY_KNOWLEDGE_API_KEY、DIFY_DATASET_ID。密钥不用发在聊天中。
管理员创建专用于本快照的 High Quality / General 知识库并验证中文嵌入模型。客户端读取已有嵌入模型身份，使用 Hybrid Search、语义／关键词各 0.5、Top-5、关闭分数阈值；weighted_score 的 reranking_enable=true 不表示额外调用重排模型。

代码依据官方 1.17.1 源码和文档核查；**当前未捕获真实实例响应，仍待真实契约联调**。首次联调先用一份批准标准；成功请求与响应自动保存在 `data/manifests/dify_responses/`（无 Authorization，人员标识脱敏，业务内容仍属本地业务数据）。保存实例 tag/commit、镜像、模型插件、模型 ID 和嵌入维度到 docs/versions.md 后，再验证契约并扩展。

```powershell
.\.venv\Scripts\uv.exe run python -m app.cli sync-dify --snapshot pilot_20260918_01
# 再执行一次，远端文档数应保持不变。
.\.venv\Scripts\uv.exe run python -m app.cli sync-dify --snapshot pilot_20260918_01
```

同步顺序为记录创建意图、建文档、等待索引、读取全部分页、检查每块唯一标识和完整索引文本、原子保存映射。任何无标识尾块、合并、重复、遗漏、禁用或文本变化均阻止发布。
数据源必须与同步清单一致，一个 dataset 不混入其他快照或无关文档。

如果创建时超时，下一次先按稳定文档名对账；不能确认创建结果时停止自动创建。检查 `sync_*.json`、Dify 文档列表与创建请求记录，确认是否存在并等待索引。不得仅删除清单盲目重跑。若确认没有任何远端创建且需要重试，由管理员保留旧清单副本后修复该条目。
同步进程异常退出可能留下 dataset_*.lock；先核对锁内 PID 已退出，再删除这一具体锁文件。不要删除整个 manifests 或数据库。

## 5. 检索评测与激活

按 evals/README.md 填写人工标注问题，条款目标必须来自已导入快照。默认 retrieval_cases.jsonl 留空，避免伪造评测。

```powershell
.\.venv\Scripts\uv.exe run python -m app.cli evaluate-retrieval --cases evals/retrieval_cases.jsonl
.\.venv\Scripts\uv.exe run python -m app.cli activate-snapshot --snapshot pilot_20260918_01
```

评测保存条款级 Top-5 命中率、多目标完整覆盖、无答案候选率和技术错误；初始门禁为存在可回答标注、命中率 ≥90%、无技术错误。多条款完整性和适用性必须另行复核，少量测试不代表业务能力。
激活前会重新回读全部分块并核对快照、数据源、映射和评测哈希；真实环境拒绝合成评测结果。
激活成功后在 .env 设置 ACTIVE_SNAPSHOT_ID，重启服务。

## 6. 服务与恢复

```powershell
.\.venv\Scripts\uv.exe run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

只有 GET /health 无需密钥。准备证据、定稿和报告查询使用 `Authorization: Bearer <本地 EVIDENCE_API_TOKEN>`。
服务身份固定为内部可信工作流，不提供公网匿名查询或用户级授权。
request_id 相同且内容相同返回保存的证据上下文；内容不同返回 409。相同 context_id 只能固定一份草稿，修改请重新创建评估请求。
数据库事务成功后才返回报告；reports 表同时保存 JSON、Markdown、验证记录。导出文件可从查询结果重建。
SQLite 在本地持久化磁盘上，单实例单 worker；不在 SMB/NFS 上共享。报告和上下文不会因重启丢失。

## 7. 容器与下一阶段

deploy/compose.yml 只定义 evidence-api。填写 DIFY_NETWORK_NAME 为官方 Dify 执行节点可访问的现有网络，然后执行 `docker compose --env-file .env -f deploy/compose.yml up -d --build`。
当前无 Docker CLI，Dockerfile 与 Compose 尚未构建或联通验收。容器镜像使用明确版本标签，部署时记录实际 digest。
SSRF 代理若阻止访问，只放行 evidence-api 等所需域名，不关闭整套防护；必须从 Dify HTTP 节点验证 /health。
阶段 D 的节点和变量交接见 workflows/workflow-spec.md；未验证前不提供可导入 DSL，也不把模型或真实图片评估记为已完成。
