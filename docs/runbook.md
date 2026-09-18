# 本地运行与分阶段联调手册

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

代码依据官方 1.17.1 源码和文档核查；本轮已通过用户配置的 Dify Cloud 实例完成真实契约联调。请求与成功／失败响应自动保存在 `data/manifests/dify_responses/`（无 Authorization，仍属于本地业务数据）；版本管理中的 fixture 另行去除业务文本与身份信息。
本轮云服务模型为 Qwen/Qwen3-Embedding-4B。云服务的运行 commit、镜像和插件版本并未由本知识库密钥暴露，不能写成已部署固定版本 1.17.1；实际可确认信息与限制见 docs/versions.md。迁移自建部署时重新锁定并验收。

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

按 evals/README.md 填写人工标注问题，条款目标必须来自已导入快照。当前 retrieval_cases.jsonl 为用户已确认的15题，预期答案在真实检索前确定。

```powershell
.\.venv\Scripts\uv.exe run python -m app.cli evaluate-retrieval --cases evals/retrieval_cases.jsonl --interval-seconds 7
.\.venv\Scripts\uv.exe run python -m app.cli activate-snapshot --snapshot pilot_20260918_01
```

评测保存条款级 Top-5 命中率、多目标完整覆盖、无答案候选率和技术错误；初始门禁为存在可回答标注、命中率 ≥90%、无技术错误。多条款完整性和适用性必须另行复核，少量测试不代表业务能力。
interval-seconds 为可选参数，默认0；本轮云端评测使用7秒以避免突发请求，未增加自动重试。发生错误的题组比例返回 null，错误响应保存后供定位；不要把403、超时或映射失败解释成无答案。
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

## 8. 阶段 D 当前入口

workflows/workflow-spec.md 是节点、变量和部署绑定的主规格。生成候选时使用本地虚拟环境：

```powershell
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode fixed --output data/workflows/fixed-observation.candidate.yml
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode vision --output data/workflows/safety-assessment.candidate.yml --model Qwen/Qwen3.5-27B --evidence-url https://实际受控服务地址
```

生成器不包含密钥。当前固定观察候选已在Dify Cloud通过真实检索／HTTP／报告保存闭环；完整视觉候选已恢复到未发布工作台，尚未完成实拍验收。
部署前由业务人员确认 config/checklist.json 的设备类别与检查项，填写真实确认记录；在Dify环境变量中同步 CHECKLIST_JSON。
两个LLM绑定同一份 start.images 和同一模型。使用同一设备的1～4张实拍图，先执行输入限制反例，再运行完整流程。
EVIDENCE_API_BASE_URL 必须指向管理员控制、Dify Cloud可达的证据服务；已有Compose内网默认主机名不能直接用于云实例。Bearer值仅通过Dify Secret配置，不放进候选文件或提示词。
本轮已使用用户提供的Quick Tunnel地址，并经明确授权保存EVIDENCE_API_TOKEN到当前工作流Secret。临时配置载荷已删除。普通无密钥候选重新导入后，务必核对Secret是否保留；星号不代表一定有有效值。
Quick Tunnel的当前地址在data/quick_tunnel/runtime.json；进程需持续运行。重新启动后按data/quick_tunnel/README.md操作，并更新Dify EVIDENCE_API_BASE_URL。不能直接重启启动脚本覆盖已经运行的服务。
完成固定观察HTTP闭环、真实视觉与评估模型、多图片关联及服务端报告核对后，才导出正式 workflows/safety-assessment.yml。阶段D未验收前不将工作流发布供业务使用。

公开图片测试资料在 data/stage_d_web/：resources.json记录来源、许可证、尺寸与哈希；input.single.json、input.multi.json、input.mixed-negative.json为表单文本，images路径用于本地选文件，不直接传入API。mixed-negative的预期分类只记录在测试证据中，不能写入模型输入作为答案提示。checklist.proposed.json为六项测试覆盖草案，仍须用户确认后填写真实确认记录并同步到Dify。
本次图片由浏览器从Wikimedia Commons已加载的原始尺寸资源下载；命令行请求返回403时已停止该下载路径。Windows文件选择器使用绝对正斜杠路径，例如 D:/RAG-Dify/data/stage_d_web/images/hwacheon-overview.jpg；每张JPEG均低于5 MiB。
Qwen/Qwen2.5-VL-32B-Instruct已实测不可用；当前生成器对Qwen/Qwen3.5-27B使用官方插件声明的enable_thinking=false。单步执行超时后需查看浏览器错误日志及运行时间，避免误读上次缓存。单步观察输出不能代替/reports/finalize的完整工作流结果。
