# 分阶段验收记录

目标范围：阶段 A～C 已完成；用户随后明确授权开始阶段 D，不进入阶段 E。当前根目录即指南中的 `mechanical-safety-rag/`。
所有终端命令使用 PowerShell 7；测试使用 `D:\RAG-Dify\.venv`。

## 阶段 C 结论：用户确认范围内已通过（2026-09-18）

用户在恢复目标后明确选择“以已批准的10条完成本轮阶段 C 验收”。本轮仅使用 GB/T 8196-2018 已签核10条；另外302条候选未自动批准。下方早期“待配置／待复核”内容为历史记录。

| 验收项 | 本轮实际证据 |
|---|---|
| 人工复核与来源 | 10条批准记录及15题标注签核哈希均通过复查；来源块、页数、文本哈希与上下文依赖验证通过 |
| 正式导入与幂等 | import-reviewed 首次 candidate，1份标准／10条；再次 unchanged，条款数量不变 |
| Dify 异步索引 | 创建成功后等到 indexing_status=completed；仅1次成功创建请求 |
| 全部分块一一对应 | 10个实际分块与预期10片段的全文、唯一标识和所属条款全部一致 |
| 真实分页回读 | page_size=3，四页分别3/3/3/1条；合并后映射哈希与数据库一致 |
| 重复同步 | 同批 sync-dify 再执行后仍为1个远端文档、10个分块，document ID不变 |
| 真实检索 | 15题完成、0技术错误；12道可回答题Top-5命中率100%，两个多条款题均找全 |
| 无答案边界 | 3道无答案题均有相似候选（候选率100%）；不能据此补造数值或认定已有答案 |
| 快照激活 | activate-snapshot 发布前再次回读校验通过；pilot_20260918_01 已激活，.env 已设置 ACTIVE_SNAPSHOT_ID |
| 本地服务 | 本地真实 Uvicorn 单worker进程 /health 返回200；不是 Dify HTTP 节点联通验收 |
| 回归测试 | `.\.venv\Scripts\uv.exe run pytest` → **66 passed in 2.32s**，2条第三方弃用警告 |

关键命令：

```powershell
.\.venv\Scripts\uv.exe run python -m app.cli import-reviewed --input data/reviewed/approved.jsonl --snapshot pilot_20260918_01
.\.venv\Scripts\uv.exe run python -m app.cli sync-dify --snapshot pilot_20260918_01
.\.venv\Scripts\uv.exe run python -m app.cli evaluate-retrieval --cases evals/retrieval_cases.jsonl --interval-seconds 7
.\.venv\Scripts\uv.exe run python -m app.cli activate-snapshot --snapshot pilot_20260918_01
```

首次连续评测的前10题成功、后5题出现403；失败记录保留在 data/manifests/retrieval_first_attempt_with_403.json。间隔7秒重跑15题全部成功，未修改预期答案、权重或阈值。表现与[官方知识库限流说明](https://docs.dify.ai/versions/3-0-x/zh/user-guide/knowledge-base/knowledge-request-rate-limit)一致，但最初403响应体未保存，不能断言其具体错误码；现已补充失败响应脱敏采集。

另一次 Workspace 模型查询确实返回403 forbidden（dataset scoped key 无授权），这是已捕获的权限错误，与检索突发403分开记录。云服务运行版本、镜像和实际嵌入维度未由现有授权接口暴露，详见 docs/versions.md。

真实证据：data/manifests/dify_responses、stage_c_pagination.json、stage_c_health.json，以及 sync_*.json / retrieval_*.json；结构脱敏后的9份真实响应与来源哈希在 fixtures/dify_cloud/。业务库现在为1份标准、10条款、10映射，未生成真实设备报告。

阶段C结束时尚未实施D/E；后续阶段D进展见文末。图片／模型闭环、Dify HTTP节点联通和完整业务验收均不在阶段C完成声明内。无答案候选不能直接当成证据支持；当前100%只代表12道已标注可回答题，不代表安全评估准确率。

## 阶段 A — 已通过模拟验收（2026-09-18）

- 命令：`.\.venv\Scripts\uv.exe run pytest`
- 实际结果：20 passed；2 条上游 TestClient 弃用警告；未访问真实模型或知识库。
- 四个接口、Pydantic 严格契约、五张业务表、schema_version=1、WAL 与短事务已实现。
- 已验证：固定模拟证据生成报告、原文与哈希回填、虚构／跨上下文／跨检查项引用拒绝、观察越界、无命中保留、不完整证据拒绝确定风险、技术故障、鉴权、真实模式禁用 fixture、幂等冲突、报告重启查询、并行隔离和 Markdown 转义。
- 报告始终 `pending_review`；测试通过不等于真实安全评估或模型提示注入测试通过。

## 阶段 B — 初次解析与整理记录（签核和正式导入见上方结论）

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

## 阶段 C — 早期离线实施记录（后续真实验收见上方结论）

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

## 首批条款复核材料（2026-09-18）

- 已按用户要求准备 GB/T 8196-2018 的10条首轮试点记录：1、5.1.1、5.1.2、5.2.1、5.3.1、5.3.3、5.3.7、5.3.8、5.3.10、5.3.13。
- AI 辅助原文对照完成后，用户已针对具体复核单明确回复“已核对并批准，复核人记为‘用户（本次对话确认）’”。查看原 PDF 封面和第6、13、14、15、16、17页；官方状态页面核查显示“现行”，适用性仍需结合具体设备另行复核。
- 修复范围条款混入标题、三处父子标题合并导致的条款编号错误、列举排版和跨页句尾；不润色条款文字。
- 输出 `data/reviewed/approved.jsonl`、`gbt8196_review/review.md`、`review_manifest.json`、页图及 `validation.json`。收到签核后，10条记录已改为 approved，写入用户指定的复核人标识和实际确认时间；条款原文与源位置未因审批改变。
- 命令（PowerShell 7）：`$env:PYTHONPATH=(Get-Location).Path`，随后 `.\.venv\Scripts\python.exe -B data/reviewed/gbt8196_review/validate_review.py`。
- 实际校验：10条 Schema、PDF SHA-256、条款哈希、来源块定位、确定性 UID、上下文引用闭合及无环检查均通过；去除排版空白和页眉页码后，10条均与 PDF 文本层逐字一致。页图已逐页辅助核对。
- 签核前，在临时数据库中验证未批准材料被 review_required 拒绝；签核后的正式导入和重复导入验证见 validation.json，测试仍只操作临时数据库。未导入业务数据库、未上传到 Dify；业务原文及页图保持在 Git 忽略目录。

## 首轮检索标注准备（2026-09-18）

- 已依据批准的10条语料准备 `evals/retrieval_cases.jsonl`：15题，其中10道单条款题、2道多条款题、3道当前快照无答案题。
- 10条已批准条款全部有单独用例覆盖；多条款题分别覆盖锐边/连接牢固性、耐久性/关闭位置。无答案题包含本快照没有的螺栓定量要求、安全距离数值和急停要求。
- 标注在真实检索前确定，未用检索结果反推期望答案。Codex 初标后，用户已明确回复“已核对15题，确认全部预期条款及无答案标注”；复核人沿用“用户（本次对话确认）”，时间和文件哈希详见本地 `data/evals/retrieval_annotation_manifest.json`。
- 可读问题表与逐题理由在 `data/evals/retrieval_cases_review.md`；标注格式严格保留 RetrievalCase 的7个字段，不把说明文字混入接口契约。
- 验证命令：`$env:PYTHONPATH=(Get-Location).Path`，随后 `.\.venv\Scripts\python.exe -B data/evals/validate_annotations.py`。
- 实际结果：15条 Schema 校验通过；用例 ID/问题无重复、目标 UID 均存在于批准语料、快照一致、来源哈希一致；单题最长48字。未运行真实检索，没有命中率或业务效果结论。
- 此集合用于阶段C首轮排错，不替代阶段E完整验收集；无答案的候选召回率不等于最终报告误引率，多条款需单独查看全部目标覆盖。

## 阶段 D — 代码及云端导入完成，真实闭环待验收

- 用户已明确授权开始阶段D，AGENTS.md同步更新范围；未扩展至阶段E。
- 实现纯标准库Code节点：图片／设备范围校验、模型观察校验、固定清单覆盖、原生检索适配、检查项汇总、prepare响应核对、context_id绑定和仅输出服务端报告。
- 同一份start.images分别连接两个视觉模型；图片ID按上传顺序生成。所有跨服务操作使用HTTP节点，Code不做网络、文件、SQLite或shell操作。
- prepare新增设备／工况／模型／工作流版本可选字段并写入报告。旧请求不含这些字段时幂等哈希保持原样；四个HTTP接口未增加或改名。
- 6项检查覆盖草案已写入config/checklist.json，但设备类别与业务确认仍为pending；真实工作流对此拒绝继续。
- 生成固定观察17节点和完整视觉19节点候选，均标记untested、服务密钥为空；两种候选已通过浏览器在当前Dify Cloud成功导入同一个未发布草稿。当前画布保留完整视觉候选。
- 原生Knowledge Retrieval节点单步执行：SUCCESS，2.542s，5条结果全部可映射回本地批准条款（5.3.7、1、5.2.1、5.3.1、5.3.3）。真实脱敏输出已进入fixtures。
- 适配Code节点使用上述真实检索缓存单步执行：SUCCESS，0.128s。没有据此宣称整条Workflow已经成功。
- 本地 `.venv` 全量验证：96 passed in 3.02s，2条既有第三方弃用警告；新增30项测试覆盖节点参数绑定、生成代码执行、完整／固定两种候选的模拟报告闭环、同设备与图片限制、检查项不得遗漏、真实Workflow响应适配、错误不得冒充空检索和旧请求幂等兼容。
- DSL参考结构来自Dify 1.17.1 / graphon 0.7.0 / DSL 0.7.0；不凭空猜第三方字段。当前Dify Cloud版本仍未被声称固定到该tag。
- 尚未取得实拍设备图片、确定设备类别／清单确认、云端可达证据服务地址；未从Dify执行/health、prepare、finalize，也未调用多模态模型完成报告。最终safety-assessment.yml暂不交付。
- 浏览器导出空白基线时未获得下载文件，因此没有把该导出动作记为交付成功；候选改由官方结构生成，并已用实际云端导入验证。完整运行验收后再导出正式版本。

实际命令：

```powershell
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode fixed --output data/workflows/fixed-observation.candidate.yml
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode vision --output data/workflows/safety-assessment.candidate.yml
.\.venv\Scripts\uv.exe run pytest
```

待继续所需：设备类别与检查清单确认、同一设备1～4张实拍图片、本项目证据服务的受控HTTPS地址及Dify Secret绑定。Dify工作台登录和模型提供方已经可用，无需重复提供Knowledge API密钥。

## Quick Tunnel 临时入口验证（2026-09-18，独立侧任务）

- 用户明确要求配置并验证Quick Tunnel。使用Cloudflare官方cloudflared 2026.9.1 Windows amd64便携版，SHA-256为2837888cc0f5d58f15b6dc478376de90b4d3ba5241c7947455d1e0a0df429712，与官方发布元数据一致。
- 本地证据API仅监听127.0.0.1:8000，使用本项目.venv、1个worker；API和隧道在隐藏后台进程中运行，未安装开机服务。入口地址及进程身份保存在data/quick_tunnel/runtime.json。
- 实际命令：`.\.venv\Scripts\python.exe -B data/quick_tunnel/verify.py`。HTTPS健康检查200；匿名和错误Bearer请求401；正确Bearer访问不存在报告404，说明鉴权通过；非法prepare载荷422；不存在的finalize上下文404。`.env`和数据库文件路径均404。
- 证书校验保持开启；公网探针的唯一probe_id可在本地API访问日志中对应到200响应。未新建证据上下文或报告，业务表数量仍为1份标准、10条款、10映射、0上下文、0报告。
- 启停脚本及操作说明保存在data/quick_tunnel/；停止脚本核对PID和精确启动时间，`-WhatIf`预演仅识别本次3个进程且未改变运行状态。
- 外部网页抓取工具未能访问该临时URL，因此不把它计为独立外部探针成功。本次已验证经过公网HTTPS入口的实际请求；尚未从Dify HTTP节点执行/health，未修改主任务的Dify工作流或Secret。
- 此为临时联调入口，电脑或进程退出后不可用，重启会重新分配地址；主任务继续时读取runtime.json的public_url并完成Dify节点验收。
