# 分阶段验收记录

目标范围：阶段 A～D 已完成本轮限定范围内的技术验收，不进入阶段 E。当前根目录即指南中的 `mechanical-safety-rag/`。
所有终端命令使用 PowerShell 7；测试使用 `D:\RAG-Dify\.venv`。

## 阶段 D 结论：技术闭环与正式DSL已交付（2026-09-19）

用户已确认普通卧式金属车床六项清单，仅使用此前批准的10条语料和公开照片。stage-d-v2曾通过单图、双图及混设备反例，随后复验暴露合法重复引用被误拦的问题；当前stage-d-v3已兼容该格式偏差，并通过同一真实失败输入回放及新一轮单图、同机双图完整流程。两个新报告均为6项检查、18处引用，原文和哈希与批准快照一致；Dify输出、SQLite和HTTPS查询一致，重复请求不新增记录，匿名查询401。

交付：workflows/safety-assessment.yml（stage-d-v3，19节点、无密钥，代码副本与本轮工作台逐项核对），本地110项测试通过。详细运行ID、失败修复、命令和SHA-256见文末；早期pending、失败及v2成功状态均保留为历史记录。报告仍为pending_review，工作流未发布，视觉误识别和条款适用性仍需专业复核；阶段E业务评测、并发及重启恢复现场验收尚未开展。

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

真实证据：data/manifests/dify_responses、stage_c_pagination.json、stage_c_health.json，以及 sync_*.json / retrieval_*.json；结构脱敏后的9份真实响应与来源哈希在 fixtures/dify_cloud/。阶段C结束时业务库为1份标准、10条款、10映射，尚未生成真实设备报告。

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
- 本次初始实现时尚未取得实拍设备图片、确定设备类别／清单确认及云端可达地址；后续HTTP闭环进展见文末。仍未调用多模态模型完成实拍报告，最终safety-assessment.yml暂不交付。
- 浏览器导出空白基线时未获得下载文件，因此没有把该导出动作记为交付成功；候选改由官方结构生成，并已用实际云端导入验证。完整运行验收后再导出正式版本。

实际命令：

```powershell
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode fixed --output data/workflows/fixed-observation.candidate.yml
.\.venv\Scripts\uv.exe run python -m workflows.build_candidate --mode vision --output data/workflows/safety-assessment.candidate.yml
.\.venv\Scripts\uv.exe run pytest
```

当前待继续所需：设备类别与检查清单确认、同一设备1～4张实拍图片。Dify工作台登录、HTTPS入口与Secret绑定均已就绪，无需重复提供Knowledge API密钥。

## Quick Tunnel 临时入口验证（2026-09-18，独立侧任务）

- 用户明确要求配置并验证Quick Tunnel。使用Cloudflare官方cloudflared 2026.9.1 Windows amd64便携版，SHA-256为2837888cc0f5d58f15b6dc478376de90b4d3ba5241c7947455d1e0a0df429712，与官方发布元数据一致。
- 本地证据API仅监听127.0.0.1:8000，使用本项目.venv、1个worker；API和隧道在隐藏后台进程中运行，未安装开机服务。入口地址及进程身份保存在data/quick_tunnel/runtime.json。
- 实际命令：`.\.venv\Scripts\python.exe -B data/quick_tunnel/verify.py`。HTTPS健康检查200；匿名和错误Bearer请求401；正确Bearer访问不存在报告404，说明鉴权通过；非法prepare载荷422；不存在的finalize上下文404。`.env`和数据库文件路径均404。
- 证书校验保持开启；公网探针的唯一probe_id可在本地API访问日志中对应到200响应。未新建证据上下文或报告，业务表数量仍为1份标准、10条款、10映射、0上下文、0报告。
- 启停脚本及操作说明保存在data/quick_tunnel/；停止脚本核对PID和精确启动时间，`-WhatIf`预演仅识别本次3个进程且未改变运行状态。
- 外部网页抓取工具未能访问该临时URL，因此不把它计为独立外部探针成功。本次已验证经过公网HTTPS入口的实际请求；尚未从Dify HTTP节点执行/health，未修改主任务的Dify工作流或Secret。
- 此为临时联调入口，电脑或进程退出后不可用，重启会重新分配地址；主任务继续时读取runtime.json的public_url并完成Dify节点验收。

## 阶段 D — Quick Tunnel 与固定观察完整闭环（2026-09-18）

- 读取并核对用户提供的Quick Tunnel运行记录，API launcher、listener和cloudflared三个PID与启动时间均一致，HTTPS /health实测200。
- 将用户提供的地址绑定到当前Dify草稿EVIDENCE_API_BASE_URL；从Dify HTTP节点执行/health：SUCCESS、HTTP200、0.615s，SSL验证开启。证据见data/workflows/dify-http-health.json。
- 初始业务探针在Dify内部失败：API key was empty，未发出业务请求。界面的Secret星号不能证明实际有值。
- 用户明确授权将本地.env的现有EVIDENCE_API_TOKEN保存到当前工作流同名Secret。使用仅包含该项服务凭据的一次性本地配置载荷完成绑定，Knowledge API密钥未包含其中；两份用于固定观察和恢复视觉草稿的载荷均已删除，未进入Git或聊天内容。
- 固定观察17节点在Dify完成整次测试运行，状态SUCCESS，开始时间2026-09-18 19:48:49，运行12.300s。原生检索后依次执行prepare、finalize和服务端结果输出；本地API日志对应GET /health、POST /evidence/prepare、POST /reports/finalize均为200。
- 测试运行ID：e1476c2f-2f20-4b3f-b1a8-e7d7d96d6e08；报告ID：rpt_5cee5f30bc244fb491c0df9dffe3cd83。报告为固定观察的软件联通测试，model_id=fixed-response-no-model，未使用真实照片或多模态模型。
- Dify输出Markdown的SHA-256为cb9f1a8e9f7550b853f70e20024b4e0f1c0ffc593637ff387315009a008b1774，与SQLite和HTTPS GET /reports读取结果完全相同；5条不同的引用／上下文条款原文及哈希均与批准快照一致。
- 最终状态validation_passed=true、review_status=pending_review；匿名查询报告401，授权查询200。通过本地.venv经同一HTTPS入口重放相同prepare和finalize，仍返回同一context/report，记录数保持1个上下文、1个软件测试报告。
- 本地证据：data/workflows/fixed-workflow-verification.json；报告导出：data/reports/stage-d-fixed-smoke.md和.json。所有业务内容保留在Git忽略目录。
- 已恢复完整视觉19节点草稿并保留HTTPS和Secret，仍未发布。恢复后的单步调试曾因Dify缓存输入缺失未发出请求，不计为额外HTTP验收；完整固定观察运行及随后HTTPS重放的成功证据分别记录来源。
- 本轮未改应用代码或依赖，因此没有重复跑96项既有单元测试；实际联调与持久化复核均使用Dify节点及本项目.venv。

剩余条件：明确设备类别并确认检查清单，提供同一台设备的实拍图片后，继续验证真实视觉、评估模型、多图片关联和最终正式DSL。Quick Tunnel是临时入口，本次12.3s仅是一例实测，不是吞吐或时延承诺。

## 阶段 D — 公开图片资源与真实视觉节点测试（2026-09-18）

- 用户授权自行检索、下载实际测试文本与图片。指定Chrome当前未连接，工具清单只显示内置浏览器；已说明替代方式，并通过内置浏览器继续Dify测试。未宣称使用了Chrome。
- 下载3张Wikimedia Commons真实摄影文件：Glenn McKechnie的Hwacheon整机图（1816×1401，237887字节）和同机主轴箱近照（1644×1443，221665字节），以及Greudin的另一台EMCO普通车床图（761×591，124046字节）。前两张采用CC BY-SA 3.0，后一张由作者释放至公有领域。原样下载，本地未裁剪、改绘或合成；近照本身含源作者标注与局部去色。
- 命令行访问源站返回403机器人访问限制，转由浏览器pageAssets取得已加载的原始尺寸图片；大小、JPEG头、尺寸和哈希均在本项目.venv核查。整机和负例的SHA-1与来源页记录一致。三图的来源、作者、许可证和SHA-256已进入fixtures/stage_d_public_images.provenance.json，图片文件留在Git忽略目录data/stage_d_web/images/。
- 基于来源说明准备input.single.json、input.multi.json、input.mixed-negative.json及checklist.proposed.json。运行及现场条件填写未知，不将网上说明当作标准证据。混图负例的输入不透露预期分类。固定清单拟采用普通卧式金属车床的现有六项防护方向；确认问题已提交用户，未收到答复前仍为pending，没有冒填人工复核人。
- 首次真实图片调用：Qwen/Qwen2.5-VL-32B-Instruct，22:54:41开始，2.237秒，FAIL；提供方403、code=30003、Model disabled，0 tokens。不作为业务无风险结果；官方服务调整公告也列出该旧模型下线。
- 换用同一提供方Qwen/Qwen3.5-27B。真实单图LLM单步：22:57:24开始，SUCCESS，47.004秒，4996 tokens；VisionResult Schema通过。原始观察包含把黄色防护构件识别为灯架等错误，已记录vision_error，未自动改写原始模型输出。
- 第一次双图单步请求超时，浏览器在2026-09-18T14:02:10.997Z记录TimeoutError。界面随后显示单图旧SUCCESS缓存；已逐字段核对输出相同，没有将它误计为双图通过；后端是否继续执行未知。
- 官方插件qwen3.5-27b.yaml（blob c5aa85ed1271fef6473bb3e002467d7d237dfcb5）声明vision和enable_thinking。Dify中显式设置enable_thinking=false后，双图实测23:05:30开始，SUCCESS，24.868秒，5963 tokens，无reasoning_content；scope_status=same_equipment，观察关联image_001和image_002，未引用清单外check_id。仍存在部件标号误识别，不据此声称风险判断准确。
- 混设备单步：23:09:08开始，SUCCESS，24.680秒，4154 tokens；scope_status=different_equipment，并区分HWACHEON与EMCO。模型的其他观察文字仍有误识别，此次只验证范围分类，不当成整条Workflow负例执行成功。
- 三次成功单步、旧模型失败及双图超时均保留独立本地记录：data/stage_d_web/vision-*.json。取得真实Dify的#files#元数据，加入脱敏fixture及契约回归；不保存签名文件URL或租户标识到Git。
- 最小代码变更仅更新候选默认模型，并为该提供方/模型显式关闭思考参数；两个视觉节点保持同一start.images绑定、原结构化Schema和错误终止方式。既有四个HTTP接口及业务数据库契约未改变。
- 完整19节点草稿已重新导入，同步两个模型节点与MODEL_ID并保留既有HTTPS和已授权Secret。草稿未发布，清单仍pending。一次性凭据载荷导入后删除，普通候选无密钥。Dify切换模型时会清空图片变量选择的现象已写入运行手册，生成器继续固定两个图片绑定。
- 实际测试命令：`.\.venv\Scripts\python.exe -m pytest tests/test_workflow_nodes.py tests/test_workflow_candidate.py` → 31 passed；模型参数契约测试加入后，`.\.venv\Scripts\python.exe -m pytest` → **98 passed in 2.83s**，2条既有第三方弃用警告。公开图片输出另经本地VisionResult及图片/检查项ID边界核对。
- 本轮上述LLM单步未执行prepare/finalize，未新建报告；数据库仍为1个固定观察软件测试上下文、1个固定观察报告。单步真实模型与此前固定观察闭环不能拼接冒充一次完整真实视觉报告。
- 重新导入后主表单曾出现上传失败；刷新草稿页面后单图上传恢复。使用真实上传图片启动完整Workflow：23:19:53开始，1.833秒、4步、0 tokens，在validate_input以“固定检查清单尚未由业务人员确认”终止，输出为空。这是预期的清单确认门禁验证，不是完整视觉成功；记录见data/stage_d_web/workflow-pending-checklist.real.json。

待继续：用户确认本轮六项检查清单后，运行单图和同机多图的完整检索、评估模型、prepare/finalize流程，验证主流程的混设备拒绝，核对保存报告并导出正式DSL。阶段D尚未完成，未扩展阶段E；公开历史照片不替代现场专业复核。

## 阶段 D — 清单确认与完整流程验收（2026-09-18～19，UI时间为Asia/Tokyo）

- 用户回复“确认”，批准普通卧式金属车床的现有六项清单用于本轮公开图片技术测试。config/checklist.json记录用户确认人和UTC记录时间；六项ID、名称及查询均与确认前草案一致。确认只针对本轮测试覆盖，不代表设备安全结论已获专业复核。
- 第一轮单图完整Workflow运行SUCCESS：2026-09-18 23:30:09开始，177.213秒，51354 tokens，15个外层执行步骤；运行ID为6ada338e-aa64-4944-be5c-192368c031b1，报告rpt_e6005763f9b24bdb9c1e90acb2fc57c9。真实视觉、6项检索、prepare、评估模型和finalize均已执行。
- 该初次报告虽通过既有结构校验，但审阅发现模型把证据ID嵌入建议正文，同时把evidence_ids全部留空，导致没有正式条款回填。此报告标记为本轮不予接受的试运行，原记录和导出备份保留，不修改数据库原报告；证据见data/stage_d_web/report-single-initial-citation-issue.json。
- 最小修复：评估提示词要求引用进入evidence_ids、正文不写证据ID；有相关标准但缺少现场条件时保留引用并使用needs_confirmation。绑定草稿的Code节点拒绝正文中出现服务生成的ev_加32位十六进制ID，阻止以正文代替结构化引用。四个HTTP接口、数据库和服务端既有引用校验不变。
- 新增4项回归先复现失败，再执行`.\.venv\Scripts\python.exe -X utf8 -m pytest` → **102 passed in 2.79s**，2条既有第三方弃用警告。清单pending反例改为显式构造pending状态，避免依赖业务配置当前是否已确认。
- 修复后的工作流版本为stage-d-v2；初次试运行保留stage-d-v1。后续真实验收结果继续记录如下。
- stage-d-v2单图完整运行：2026-09-18 23:42:38开始，SUCCESS，114.266秒、51161 tokens、15个外层执行步骤；运行ID f18b14b5-1e56-4268-b59d-7c8e3ac8711d，报告rpt_3a6f1fdd41b1416797fb4882139ecd7f。6项检查、18处结构化引用，全部回填自允许证据。Markdown SHA-256为e33d46bb9adb842429356cb6938f5e5f477d81d8d039219c6801df47c7b168f8。
- stage-d-v2同机双图完整运行：2026-09-18 23:48:12开始，SUCCESS，155.579秒、56781 tokens、15个外层执行步骤；运行ID 6d20f2b7-2d31-4a62-9ae6-8a8d69571e83，报告rpt_5bb2c50e656b4a1c99483ed28d05e73b。6项检查、18处引用，Markdown SHA-256为f7e71aaa1b7b6384f5edba42a5942ada36420c61b1e2aef852c771dbca709edb。
- 双图视觉节点原始输出scope_status=same_equipment，6项原始观察引用image_001及image_002。读取两个LLM节点本次实际输入，文件名、related_id、MIME、大小和顺序完全相同，且与最终报告image_manifest一致；证据见data/stage_d_web/multi-image-binding.real.json，没有保存签名图片URL。
- 两个报告的Dify输出哈希与SQLite及鉴权HTTPS查询一致；10条不同的引用／依赖条款原文、哈希、标准身份和源页位置均与已批准快照一致。以原始请求重放prepare和finalize返回相同context/report；匿名读取401。运行脚本来源为本地.venv经相同HTTPS入口，原始模型与报告创建来源为Dify Workflow，两类证据分别记录。
- 完整混设备反例：2026-09-18 23:59:40开始，2026-09-19 00:00:17结束；37.315秒、4398 tokens、6步。即使输入勾选同设备，仍在checks节点因两张照片属于不同设备而终止；未进入Iteration、prepare或finalize，输出为空。前后数据库均为4个上下文、4个报告，包括1份固定观察报告、1份不予接受的初次试运行和2份最终验收报告。
- 正式交付workflows/safety-assessment.yml，与已导入并运行的候选解析结构和值完全一致，统一UTF-8/LF。候选SHA-256为910ed9a8e0ddd8bcfee4149e1d7c3de067e066dfaff8fc1b950d431584380e99，正式文件SHA-256为fd966928c81076c11d3213a1c12719e6b237240fcfa6f74616bb643c1b06bb97。交付方式为官方结构生成后实际导入和运行验证，不冒称从Dify导出下载成功。
- 验收文件：data/stage_d_web/workflow-success-runs.real.json、report-single-verification.json、report-multi-verification.json、workflow-mixed-negative.real.json、delivery.json；报告导出为data/reports/stage-d-single-real.*及stage-d-multi-real.*。图片、报告、数据库和凭据均未提交Git；所有一次性凭据载荷均已删除。
- 正式DSL加入交付回归，防止文件中的关键门禁代码、提示词、确认清单与当前源码脱节，并检查最终输出必经finalize和Secret为空。最终执行`.\.venv\Scripts\python.exe -X utf8 -m pytest` → **103 passed in 3.15s**，2条既有第三方弃用警告；`git diff --check`通过。

持久化、原文及重放验证的实际命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B data/stage_d_web/verify_report.py --case single --report-id rpt_3a6f1fdd41b1416797fb4882139ecd7f --dify-markdown-sha256 e33d46bb9adb842429356cb6938f5e5f477d81d8d039219c6801df47c7b168f8
.\.venv\Scripts\python.exe -X utf8 -B data/stage_d_web/verify_report.py --case multi --report-id rpt_5bb2c50e656b4a1c99483ed28d05e73b --dify-markdown-sha256 f7e71aaa1b7b6384f5edba42a5942ada36420c61b1e2aef852c771dbca709edb
```

阶段D技术验收完成。剩余风险：公开图片中的部件、材质和防护状态仍有模型误识别，整改建议及适用性未完成专业业务复核；这两例运行不构成准确率或性能承诺。工作流未发布，Quick Tunnel为临时入口，当前仅一份标准的10条语料；阶段E业务验收、真实现场资料、并发及重启验证、自建容器部署均未因此被宣称完成。

## 阶段 D — 合法重复引用兼容性修复（2026-09-19）

- 按用户要求再次复验，单图于11:48:09开始，在188.993秒后被finalize_body拒绝，未执行HTTP定稿；遵照“遇阻塞先汇报”的要求，当时停止双图测试。运行ID为0d366972-e6cc-4ce4-8ccc-a3837074ccad，已保存证据上下文ctx_c03fdde2f91f4c128953fb33241a6ee3，没有对应报告。
- 只读核查原始响应：6项finding各有3个合法evidence_ids，观察归属也正确；6个risk_description另重复出现9处同样的证据ID。原始JSON与structured_output一致，线上提示词已包含禁止规则。失败来自“正文出现ID即拒绝”的格式策略，并非引用数组为空、未知引用或鉴权故障。
- 用户明确要求修复、减少过严校验、完成验收后提交Git。最小修复仅调整finalize_payload：正文中服务证据ID必须是该finding已声明的evidence_ids子集；结构化引用仍先验证属于该检查项允许集合。合法重复可继续，未登记、未知及越权引用仍拒绝；不改写正文、不自动补选或删除证据，四个HTTP接口和服务端校验不变。
- 新增回归先复现4项失败；修复后节点测试40项通过。暂不包含旧正式DSL一致性检查的回归为109 passed、1 deselected，2条既有第三方弃用警告。正式DSL随完成验收的v3配置同步后再执行全量测试。
- 通过已有Dify界面原位更新8个共享代码副本，并逐一回读SHA-256与本地候选核对；只修改非敏感WORKFLOW_VERSION为stage-d-v3，未重新导入或在浏览器读取、重填Secret。接口核查正常使用本地既有服务凭据，没有生成凭据导入载荷，鉴权及已配置HTTPS地址保持原状。
- 12:25:17使用同一真实失败输入单步回放修复后的finalize_body，SUCCESS、0.115秒、0 tokens；输入上下文和模型草稿与失败现场逐字段一致，返回的6项finding及18个引用未改写。该回放不调用模型或HTTP定稿，不作为完整流程验收；记录见data/retests/citation-compatibility-20260919/real-failure-replay.json。
- v3单图完整运行：2026-09-19 12:30:59开始，SUCCESS，131.370秒、50990 tokens、15个外层执行步骤；运行ID为31ead7da-7001-45a3-bbf0-9850f097dbfa，报告rpt_160f85fc8ad243b59fe6afa83a8d62ea。Markdown SHA-256为070b9e82e464235a40f4745f1546215175ea8f1d7850f7240d32b1484e5a4f65。
- v3同机双图完整运行：2026-09-19 12:38:01开始，SUCCESS，241.057秒、55410 tokens、15个外层执行步骤；运行ID为508ac013-9e74-4c2b-a1a6-a04fb1c22e98，报告rpt_6037a1b544af4e039073965f47506f2b。Markdown SHA-256为7b83f13e945668ffb036e3df2caaebdbf9ceaa1337310fa70280f14b90393f0b。
- 两份报告各含6项检查、18处引用；10条引用及依赖条款的原文、哈希、身份和源页位置均与批准快照一致，观察和证据归属通过核对。Dify输出、SQLite和HTTPS查询一致；重放prepare/finalize保持同一context/report且数量不变，匿名查询401。双图报告包含image_001和image_002及对应上传标识。
- 本次新生成的两份报告正文未出现重复证据ID；兼容性分支的真实验证来自前述同一失败输入原样回放（6处字段、9次重复ID），不能把普通正例冒充触发了兼容分支。
- 正式DSL同步v3代码、版本及工作台已配置的HTTPS地址，SHA-256为e389dcd26e401323e4d6a85c709163158ac0b12dec18a708258e9f008830e8c5。再次执行`.\.venv\Scripts\python.exe -X utf8 -B -m pytest` → **110 passed in 3.02s**，2条既有第三方弃用警告；包含正式DSL与源码一致性检查。
- 本轮证据及报告独立保存在data/retests/citation-compatibility-20260919/：real-failure-replay.json、expected-code-hashes.json、report-single.*、report-multi.*及对应verification.json。没有覆盖先前报告，也没有将报告、数据库或凭据提交Git；原失败上下文保留，没有为其补造报告。测试后业务库为7个证据上下文、6个报告。

本轮完整报告核对的实际命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B data/retests/citation-compatibility-20260919/verify_report.py --case single --report-id rpt_160f85fc8ad243b59fe6afa83a8d62ea --dify-markdown-sha256 070b9e82e464235a40f4745f1546215175ea8f1d7850f7240d32b1484e5a4f65
.\.venv\Scripts\python.exe -X utf8 -B data/retests/citation-compatibility-20260919/verify_report.py --case multi --report-id rpt_6037a1b544af4e039073965f47506f2b --dify-markdown-sha256 7b83f13e945668ffb036e3df2caaebdbf9ceaa1337310fa70280f14b90393f0b
```

结论：已修复合法重复引用导致的整单失败，未放宽引用身份、检查项范围、观察归属或证据完整性要求。提示词、模型、检索配置和证据输入内容未改变；不加入自动重试、自动删字或证据补选。模型对事实和适用性的判断仍需专业复核，正文可能含冗余ID或模型复述，不能据本次两个成功样本承诺所有后续运行稳定通过。Quick Tunnel仍为临时入口，工作流未发布，未扩大到阶段E。

## 本地测试台 — 页面与任务持久化（2026-09-20）

- 用户已确认实施本地前端和源码交付扩展，详见 docs/portal-plan.md。基线 d835270、阶段 D v3；先阅读指南及现有代码，新建 codex/local-review-portal 分支，保留旧试点目录和四个接口。
- 新增 app/portal、HTML/原生 JavaScript 页面、独立任务数据库、上传去重与人工复核接口。旧试点配置不自动带入新实例。引入 python-multipart 与 Pillow，用于上传及实际图片格式校验，锁定于 uv.lock。
- 工作区 .venv 执行 python -X utf8 -m pytest -q：118 passed，2 条原有第三方弃用警告；新增 8 项覆盖无效/加密/页数超限 PDF、上传去重、刷新后持久化、CSRF、版本指针和运行歧义。node --check app/static/portal.js 通过，git diff --check 通过。
- 当前为页面与任务基础提交，解析/发布 worker 和界面已接线，Dify 版本隔离及 Workflow 客户端尚待下一提交完成；未将模拟测试记为真实闭环通过。未新增人工批准条款，未改动线上 Dify 或旧数据库。

## 本地测试台 — 完整解析、人工复核和知识版本隔离（2026-09-20）

- 浏览器实际上传 test_files/0 中 GB/T 8196-2018（34页），后台使用独立 .venv-mineru、MinerU 4.0.2、all/zip/standard/auto 完整解析，得到117候选，34页覆盖完整；上传、归档、任务持久化与候选页面均实际运行。来源 SHA-256 与旧试点一致。无候选被机器自动批准。
- 浏览器原内嵌 PDF 未显示，增加 pypdfium2 原页渲染缓存；已在同页实际核对封面显示与页面切换。前端仍为 HTML/原生 JavaScript，无 Node 构建。原文件未修改。
- 用户明确确认新测试台沿用10条既有批准原文、依赖与检索标签。新解析8条文字逐字相同，2条恢复为原批准原文；所有来源页码一致。复核比较保存在 data/portal/acceptance/ten-clause-review.*。已通过页面登记首版4条人工批准，其余候选尚未发布。
- 专用知识库 mechanical-safety-local-portal 已创建；经用户授权创建仅限该库的密钥并保存在 .env.portal。使用官方 Service API 实际配置 High Quality、Hybrid Search、Qwen/Qwen3-Embedding-4B 和 rag_snapshot_id 字符串字段。未修改旧试点知识库。
- 单知识库多版本逻辑只在门户显式启用：同步为每版赋予并回读元数据，登记历史分区逐块核对，外来文档阻止发布；检索自检的 metadata_filtering_conditions 嵌套在 retrieval_model 内。证据服务仅接受已登记发布且 active 的版本，旧单快照模式保持原行为。
- 首个4条版本在真实元数据回读时被阻止：Cloud 对未设置元数据的文档返回 doc_metadata=null；保存脱敏真实 fixture，适配为“尚未绑定”，仍不算验证通过。修复后恢复同一任务和同一文档，当前正运行真实检索门禁；此处未提前宣称发布成功。
- 工作区 .venv 全量测试：137 passed，2条既有弃用警告；随后真实 null 元数据新增回归及分区测试2项通过。覆盖缺页、缺失/未确认图表、未知边界、拆分合并、编辑与依赖批准失效、跨版本命中拒绝、外来文档、未发布版本和持久化任务边界。界面轮询优化为数据变化时才重建列表，避免打断选择。

## 本地测试台 — 真实报告闭环与开发者交付（2026-09-20）

- 新应用“机械设备安全评估（本地测试台）”独立于旧stage-d-v3。用户逐项授权专用Knowledge密钥、独立8002 Quick Tunnel、新应用Secret和Workflow API发布。按空Secret/无已发布知识版本→发布→立即停用Web App→绑定Secret并更新发布的顺序实施；最终界面确认Web App=停用、后端API=启用、MCP=停用。旧8000服务、旧应用和旧业务库未改动。
- Workflow密钥因浏览器与系统剪贴板未同步，最终由用户手动填写并修正，本地GET /parameters实际鉴权通过（7项输入）。没有把凭据写入Git或报告。已授权的一次性证据Secret导入文件使用后删除。尝试的一次性本机配置通道未启动成功，未留下文件或监听端口，未改变系统防护配置。启动脚本初版也出现外部文件访问/消失异常，最终采用可检查的Python进程启动器和薄PowerShell入口，实测启停通过；未断言无法证明的拦截原因。
- 真实扫描PDF GB 16454-2008：10页完整覆盖、90候选，全部待复核。与文本版34页/117候选合计44页/207候选；仅用户再次明确批准沿用的GB/T 8196-2018十条参与发布。页面逐项记录实际用户确认人；不是AI代替专业人员新增审批。
- V1 portal_6bcc6616a6f5feea9fe8868b：4条、1文档/4分块；4道可回答题全部命中。V2 portal_6478a1021d2231b9be0b1e2b：10条、1新文档/10分块；12道可回答题全部命中，多目标全部找全。两版均另测3道无答案题，仍返回相似候选，不能据此宣称无答案判断准确。
- 原生页面提交单图任务 job_1ef241349d044062898ad23bfd31272e，固定V1。Dify运行2bdce82c-babf-47e7-9549-bf9b734302e4，SUCCESS，117.810303s、20994 tokens、15步；报告rpt_38405a87ca73434e910e24e23ed2ebe5。
- 原生页面提交同机双图任务 job_93f2c44cbe774ee28f403ad114570cad，固定V2。Dify运行86530327-fd3f-451e-a958-56d5dc1a1a9e，SUCCESS，143.534795s、55313 tokens、15步；报告rpt_715e9da4baed4835827ab5773371d57a。
- 两份报告均6项检查、18处结构化引用，分别核对4/10条不同依据及依赖，原文、SHA-256、标准身份和PDF来源位置与对应不可变版本一致。Markdown哈希分别021105c70736b9eb6be88dc02dfe9793cd8994fdb951f05d9edfe30d327e45ba、ee05183f0ed2bf46215becd93f639a6ce746967b5c9a0efe5fcdb177b5f93309。图片顺序、实际上传ID、输入工况、运行ID、知识版本与报告一致；本机SQLite、GET回读及鉴权公网HTTPS结果一致。匿名报告查询401。
- 混设备任务job_180455396ff34795b7c93cb5b2303632，运行ef39bfd6-8928-4cf1-9199-9ab7bad2aee6，FAIL，23.159020s、4275 tokens、6步；build_checks明确区分HWACHEON与emco并拒绝同机范围。无对应证据上下文、无报告。页面显示失败，报告接口409；未展示旧成功报告作为本次结果。
- 两版同时存在时，真实过滤检索分别只返回各版文档；把V1真实命中提交给V2被502 mapping_error拒绝，未发布版本被409 snapshot_not_allowed拒绝。V1已保存报告完整JSON哈希在V2发布后不变。再次sync当前版本：远程文档2→2，远程写请求0，历史分区及当前10分块全部复核通过。
- 启停脚本使用PID及精确创建时间、固定本机端口，-WhatIf预演与实际停止/重启通过。重启后两份报告JSON哈希不变，Markdown/JSON下载与保存内容一致。失败任务通过页面恢复后只查询原运行ID，仍失败且没有新报告；阶段历史保存本次对账与错误。断流和创建结果未知的禁止盲目重发由模拟契约/持久化测试覆盖，本轮未强制中断正在运行的真实模型请求。
- 页面实际验证PDF原页预览、4条/10条范围预览、明确同版本替换确认、单/双/混图提交、保存报告卡片、引用及下载入口。补上未保存编辑保护并真实验证阻止批准，测试编辑未提交；无已批准内容变化时发布按钮和后端均拒绝重复索引。列表只有数据变化时更新，避免刷新打断复核选择。
- 交付app/portal、app/workflow_client.py、模板/静态资源、Workflow模板/生成器、PowerShell7初始化/诊断/启停/导出脚本、CONTRIBUTING.md及Portal运行/API说明。前端源码经固定版本Prettier整理为可读格式，不引入运行或构建依赖。
- 最终本机验证：`.\.venv\Scripts\python.exe -X utf8 -m pytest -q` → **144 passed in 4.74s**，2条既有第三方弃用警告；`node --check app/static/portal.js`、PowerShell脚本语法检查、`git diff --check`通过。原110项基线全部保留。

本地真实证据位于data/portal/acceptance/：ten-clause-review.*、v1-report-baseline.json、workflow-runs.real.json、reports-verification.real.json、version-isolation.real.json、repeated-sync.real.json、restart-and-recovery.real.json。解析包、数据库、报告、测试照片、密钥和实际绑定DSL均不进入源码包。

剩余边界：Quick Tunnel依赖本机进程、地址可变化；公开历史照片仍有模型误识别；报告均pending_review。仅一份标准十条语料和普通卧式金属车床六项检查，不扩展为阶段E专业业务验收。新开发者仍需自己的Dify/模型凭据及HTTPS入口；没有承诺全新Windows机器或其他硬件上的MinerU安装/推理必然成功。未知远程运行ID及残留同步锁需人工对账，不自动重复创建；多用户部署、更多设备和自动清理历史索引留待后续。

### 源码包独立目录复验

- 提交35cf1a0从干净Git HEAD导出112个源码文件，确认包内无.env/.env.portal、data、test_files或虚拟环境。解压到tmp/portal-delivery-35cf1a0，工作目录切换到解压源码后，仍使用本工作区 `.venv\Scripts\python.exe -X utf8 -m pytest -q`：**144 passed in 4.62s**，2条既有弃用警告。该复验验证无业务数据/本机配置的源码可测试，不等同全新机器安装或真实Dify开箱免配置。
- 导出前扫描112个当前源码文件：本机实际服务凭据精确匹配0处；已检查的196个历史blob匹配0处。检查范围为当前已知凭据，未声称通用扫描能够证明不存在任何未知秘密。Git没有配置远程仓库，没有创建、推送或公开源码。
- 本条记录为源码交付复验补记；最终源码包由包含本记录的Git HEAD重新导出，应用代码与已复验源码保持相同。

## 本地测试台 — 易用性完善第一批（2026-09-20）

- 用户已确认实施易用性计划：本机页面填写密钥并由后端保存；标准条款和输入工况复核；单库权限、向导引导 Dify 准备；页面管理临时隧道；保持 Workflow 结构及七项输入不变，不增加模型外的诊断分支。授权在项目内按计划推进并使用 Codex 内置浏览器调试。
- 新增配置草稿、空闲应用控制、真实只读诊断、错误脱敏与任务诊断包。诊断不依赖 worker 已正常运行，仅使用有界只读请求；解析、索引和远程 Workflow 仍在独立 worker。新增来源/上下文选择器、检索标注表单、图片预览顺序和首次测试指引。
- 使用工作区 .venv，原144项回归保持通过；新增14项配置/诊断/脱敏/契约测试后，全量 **158 passed in 5.23s**，两条既有第三方弃用警告。真实 /parameters 的七字段与限额已采集为不含凭据的契约fixture。
- 已通过 Codex 内置浏览器看到新向导并运行实际诊断：本机解析器、数据库、worker、Knowledge鉴权/模型配置/元数据、Workflow鉴权/输入字段均通过。本机访问原临时HTTPS地址遇到 TLS UNEXPECTED_EOF；页面准确显示失败及技术详情，没有标为全链路通过。公网入口恢复和新页面完整流程验收在下一批继续。
- 修改前记录门户原有两份报告完整JSON哈希和两版知识状态于data/portal/usability-acceptance/before.json。未变更业务批准范围或旧阶段D应用。

## 本地测试台 — 易用性恢复验证（2026-09-20）

- 分支 codex/portal-usability，第一批实现提交70310f9。本轮在内置浏览器实际启动独立8002托管隧道、保存并应用非密钥配置、同步专用Workflow HTTPS变量并发布。先发现worker子进程隧道随配置重启退出的缺陷，再将诊断/隧道控制移到门户；回归测试验证worker不领取控制任务，真实配置应用后隧道PID保持、HTTPS200。旧8000与阶段D应用未改动。
- 服务配置应用冻结草稿并核对文件revision；启动失败仅撤销本次写入，不覆盖应用期间的外部修改。新增并发修改/启动失败恢复测试、无效数值配置保留身份测试。启动/初始化脚本增加无Python依赖的静态排错页，未调整系统保护策略。
- 新增知识库远端文档归属实际诊断；草稿轮换证据密钥明确待应用后鉴权，不误报401或已通过。页面支持空筛选保护、保存/应用按钮互斥、过期隧道地址禁用和任务日志手动刷新。
- 内置浏览器真实上传公开历史车床图，job_5b0b1a3300b7487781b45518e1c2f0b2，Dify run 55703935-3323-49a8-84e0-f21ce2b94ed1，102.370679秒成功，报告rpt_7743e37d02f14f2f970e2b2b062a836f。页面显示六项检查和下载入口；70条任务事件含66条经过白名单过滤的节点事件，没有保存原始模型输入输出。报告完整JSON哈希244147dfb58df3a25be02d056b69e44c673838a51022006be1ec4e7f52767461。
- 真实只读诊断13项全部通过，其中最后一项引用本配置上述真实保存/回读记录；诊断自身没有调用模型。验证信息保存在data/portal/usability-acceptance/live-diagnostics.json及report-verification.json。原两份报告JSON哈希、原两版发布状态完全未变。Dify访问点页面再次确认公开Web App停用、后端API启用、MCP停用。
- 页面实查已批准/条款搜索、原PDF第16页与来源块对照、可读依赖选择、零结果禁用操作、发布预览表单、原内容无变化时禁用重复发布。没有新增人工批准或更改已批准原文。
- 工作区 .venv 执行 python -X utf8 -m pytest -q：165 passed in 5.45s，2条原有第三方弃用警告。JS语法与Prettier检查通过。真实诊断失败的TLS原因被前端准确显示后已恢复；不是把fixture当成云端联调。
- 本批后继续做干净源码目录/空配置启动验证及最终交付复查。范围仍为阶段D技术测试，Quick Tunnel和模型判断的原有限制仍在；陌生开发者必须配置自己的Dify及模型凭据。

## 本地测试台 — 干净目录首次启动验收（2026-09-20）

- 从ea196a4干净Git HEAD导出123个源码文件，解压tmp/portal-usability-ea196a4。无配置/业务数据时，使用工作区.venv运行pytest：165 passed in 5.66s。随后在该独立目录运行deploy/init-portal.ps1，实际创建本目录.venv、安装锁定依赖并初始化空数据；未复制原Dify密钥。
- 故意在缺少本目录.venv时执行启动脚本，生成startup-bootstrap.html。之后用错误页数配置启动，页面保持可用并提示修复；通过内置浏览器改正、保存草稿、应用，只有门户进程的实例成功启动证据服务和worker。
- 空实例实际诊断准确显示Knowledge/Workflow/HTTPS三项未配置，本机健康503被识别为空库而非网络故障。通过页面实际上传同一34页标准，MinerU产生117候选、0条批准、0个已发布版本。无效PDF负例返回invalid_pdf并展示stage/request_id。该演练复用本工作区已安装的.venv-mineru 4.0.2，不宣称验证了全新机器权重下载或新Dify账号完整闭环。记录：data/portal/usability-acceptance/clean-start.json。
- 修复演练发现的默认值恢复边界：原无效值改回安全默认值时，即使生效配置指纹相同，也必须清除启动修复提示；变更清单显示实际被修正的字段。新增回归测试，并将修复加载到隔离实例，通过页面仅修改该数值再次真实恢复；记录repair-only.json。
- 根工作区.venv全量最终代码回归：166 passed in 8.36s，两条既有弃用警告。JS语法、PowerShell语法和git diff --check通过。演练实例已停止，原门户按登记脚本重新启动；完整重启后原临时地址已过期，页面正确禁用填入旧地址，并已创建/绑定新的专用隧道。
- 对原混设备失败任务恢复/对账，只查询原run ef39bfd6-8928-4cf1-9199-9ab7bad2aee6，没有创建新运行；页面给出equipment_scope_error、原因及诊断下载入口。已知配置凭据扫描277个可达历史blob，精确命中0；此结论仅覆盖已知凭据。未配置Git远程或发布源码。

### 最终恢复与双图闭环

- 原测试台恢复后，页面实测选择三图、移除异设备图、将整体图移到首位，再提交同设备双图。后端文件哈希及报告image_manifest顺序回读一致，确实只上传两图。job_5e581372699d439d91d4d470f17d9d7e，run 350b4604-7322-413c-ac0c-ed8254423913，用时124.561767秒，报告rpt_ef71d7e0f7ba48b29a3e86955c79322e成功保存，validation_passed=true、pending_review。完整JSON哈希b1d454fb2f7a4d28ebd96180662346e369219e2d8353b4c7a03ba78881b784eb。
- 之后从页面再次运行真实诊断：13项通过，真实链路项关联上述新报告；final-double-image.json、final-diagnostics.json及脱敏任务ZIP保存在data/portal/usability-acceptance。旧两份报告及两版知识状态仍与变更前一致，没有新批准条款。
- 最终内置浏览器验证：新成功报告可见；切换混设备失败诊断时旧成功报告隐藏，防止关联混淆。Dify最新发布版的Web App仍停用，后端API启用，MCP停用。门户及8002服务保留运行，托管隧道为临时入口，实际地址见本机配置与managed-tunnel.json。
- 交付范围：源码、锁文件、配置/Workflow无密钥模板、测试、运行手册和本验收记录。每个开发者仍需自己的专用Dify知识库/工作流/模型配置，并人工复核标准。空目录演练和原专用云环境的真实报告验证分别记录，不声称在全新Dify账号中完成免配置验收，也未开展阶段E业务准确性评测。

### 最终源码包复验

- a48aa97源码ZIP解压到tmp/portal-final-a48aa97；在该目录使用工作区 `.venv\Scripts\python.exe -X utf8 -m pytest -q`：**166 passed in 5.88s**，2条既有弃用警告。ZIP有123个文件及15个目录项，无运行配置、data/test_files/虚拟环境，当前已知凭据精确命中0。记录final-archive.json。
- 本记录是文档补记；最终ZIP由包含此记录的干净HEAD重新导出，应用代码、测试和依赖与已复验的a48aa97相同。仅交付本地源码包，未推送远端。浏览器已保留最新成功报告；未发现本轮最终页面的未处理JavaScript异常。

## Windows 开发者预览版 — 文档与交付入口整理（2026-09-20）

- 按新的目标只整理上手/发布材料，不扩大产品功能。修改前核对f73c6f2干净工作区、架构指南、入口代码、启动脚本和历史DSL；创建codex/windows-preview-docs分支。
- README以8001门户为推荐入口，旧8000/单快照内容集中到docs/legacy-stage-d.md；旧手册和工作流规格增加历史提示。运行手册只保留一条首次启动命令，各步骤列出成功标志/失败入口；集中Windows、PowerShell7、Python3.12/Launcher、Dify/模型/网络准备条件及远程数据去向。
- 新增docs/first-test.md，提供自主获取PDF、公开历史图片来源/署名/许可、工况文本、条款复核、检索标注与报告判据。说明源码没有原试点10条知识库，data路径是运行产物。图片来源页及官方标准检索入口已在线复查，未重新下载业务材料或复制标准原文。
- workflows/safety-assessment.yml仅改6处：应用名称/描述、HTTPS、SNAPSHOT_ID、DATASET_ID及检索节点dataset_ids。19节点代码、边、提示词与六输入契约未变，Secret仍为空。两份交付DSL均使用占位绑定；新门户继续引导页面生成当前环境七输入DSL。已配置Dify应用未改动，未重写Git历史。
- 本地工作区.venv执行 python -X utf8 -m pytest -q：166 passed in 5.62s，两条既有第三方弃用警告。扩展既有DSL契约测试，验证公开占位值、env/检索库一致且无临时隧道地址。34个本地文档链接/锚点、7个PowerShell命令块语法通过，首次启动命令计数=1，git diff --check通过；详情保存在data/docs-preview/document-check.json。
- 本轮没有重新运行MinerU/真实Dify，旧真实验收记录保留其原始上下文。浏览器仅查看当前门户配置页面；截图导出的data:导航被浏览器URL安全策略阻止，未绕过。源码包不含新的页面截图；不影响上述高优先级文档/模板整理。一次临时截图保存页命令未执行成功，经检查没有生成目录或8017监听，未留下辅助服务。
- 新增docs/windows-preview-release.md发布说明，保留未指定开源许可证、需自备云端凭据/合法资料、单机/临时隧道/专业复核限制。当前不创建或推送远程仓库，也不代替所有者决定公开许可。
- 补齐发布说明后的最终检查：39个本地文档链接/锚点全部有效，126个当前源码文件的已知配置凭据精确匹配0处；记录data/docs-preview/release-check.json。没有改变运行时源码、依赖或业务处理契约。

## 自动整理与集中复核 — 第一批实现（2026-09-20）

- 基线4a6220c，先读取指南及现有解析、复核、发布与前端实现，分支codex/assisted-standard-review。增加可追溯规则建议，不新增LLM、依赖或数据库表，不修改Dify工作流结构及四个证据接口。
- 实现标准号/年份/名称/范围预填、条款层级与父条款/范围/引用建议、缺页/空页/编号/跨页/图表/数字单位/阅读顺序检查；既有记录按读取时规则计算，新解析另保存元数据建议。机器内容仍待复核，状态和核验来源不由规则捏造。
- 增加批量对照、异常集中处理、建议关联采纳和人工批准API，基于文件revision、完整payload/基准/规则检查哈希防止过期确认；重用原批准门禁和事务审计。完全相同文件去重同时核对实际归档哈希；归档变化拒绝沿用。
- 同标准同版本文件及本文件历史批准记录提供变更/删除/未变/受依赖影响对照。新文件未变内容仍需确认来源，不把旧批准直接附到新PDF。自动检索问题仅作为草稿，每题确认记录进入发布任务，修改后的问题在页面重新取消确认。
- 工作区.venv执行 python -X utf8 -m pytest -q：181 passed in 6.86s，2条既有第三方弃用警告。15项新增用例覆盖预填非批准、独立编号标题/表格数字、异常类别、批量原子性/五项确认、依赖影响、归档变化、问题确认和重复文件保留记录。JS语法、Prettier与git diff --check通过。
- 对现有门户两份真实解析结果只读计算：GB16454扫描标准90候选，规则异常6/无规则疑点84；GB/T8196标准117候选，异常待处理27/无规则疑点80/既有批准10。数量只反映当前规则，不代表OCR准确率；未新增真实批准或发布。变更前2份文档、4份报告及2版发布状态哈希存于data/portal/assisted-review-acceptance/before.json。浏览器交互及交付验证继续在下一批完成。

## 自动整理与集中复核 — 界面、结构建议与交付验证（2026-09-20）

- 首批提交e9669da后，用不含Dify凭据、没有worker的隔离合成资料实例进行内置浏览器操作。原文PDF明确标示SYNTHETIC UI TEST ONLY：变更10mm→12mm、受影响依赖、新增/删除项均可见；未确认上下文时批量批准被拒绝；对照原PDF并采纳建议、完成五项确认后5条批准，数字疑点1条保持待复核。异常批量选择框禁用，可进入单条处理。审核动作入独立审计库，没有产生远程发布任务。记录browser-synthetic.json。
- 自动生成5道合成问题草稿；未逐题确认时提交被前端阻止，修改文本后确认取消；重复预览同一范围保留已编辑问题与确认。预选目标排在前面并可展开全文；后端对draft_问题要求草稿来源与完整确认，发布任务保留case_review。人工标注原结构仍可使用，机器草稿不能通过省略来源冒充人工标注。
- 真实扫描标准的页面实际预填编号、年份、名称与范围及PDF出处；状态、核验日期、来源仍空白。实际重复上传原GB/T8196 PDF，返回已复用已有解析与复核；2份文档、4份报告完整JSON与2版知识状态哈希均与before.json一致，真实批准仍为原10条。preservation.json记录保留检查；没有批准新真实条款、重做索引或调用模型。
- 对真实MinerU归一化产物回放新分片规则，原90候选可形成102、原117可形成133；增加的是独立编号标题（分别12与16个），没有重复路径。最初“路径应与旧分片完全相同”的验证假设因此不成立，已按新增结构建议和来源分区验证。没有在读取或去重上传时覆盖旧候选；现有第3章可分别看到13/17段建议及全文，待人工确认应用。real-rules-replay.json为真实产物规则回放，不冒称重新执行了MinerU。
- 增加历史结构建议应用：仅原文/编号/备注/上下文均未经人工修订的待复核段可按完整来源分区整理；保护批准和修订记录，保留原来源并撤销受影响依赖，所有新段仍待复核。来源/页覆盖/资产问题不放行；未编号前缀可以继续整理，但仍不能批准发布。测试覆盖过期建议、来源守恒、批准/人工修订保护、未编号前缀门禁及只撤销实际依赖。
- 旧文件核验日期/来源变更单列，适用范围等实质信息变化影响全部条款；相同标准已有批准编号写法会用于待确认预填，保护身份稳定。新旧文件共享条款UID时，发布阻塞链接优先打开本次选中的文件。只读对照显示基准该条是否曾批准，避免把整个基准文件当成已批准。
- 原门户与worker已加载最新实现，8002证据服务与原HTTPS地址保持；最新13项只读环境检查均通过，model_invoked=false，真实链路项仅引用此前已保存的报告。为覆盖门户崩溃/开发重载后的隧道进程关系变化，停止脚本独立核对托管隧道PID/创建时间/8002来源；WhatIf列出的仅为本实例三角色及登记隧道，没有实际终止它们。
- 工作区.venv全量 python -X utf8 -m pytest -q：**192 passed in 7.67s**，2条既有第三方弃用警告（原166项+新增26项）。JS语法、Prettier及PowerShell停止脚本语法通过，git diff --check通过。34处本地文档链接/锚点有效，130个当前源码文件中已知服务凭据精确匹配0；记录source-audit.json。后续仅微调基准状态显示文案并通过JS语法检查。
- 本轮采用rules-v1而非新LLM，规则可能漏检或误报，无疑点不代表OCR正确。状态核验、适用性、条款批准和最终报告仍需人工；未进入阶段E业务准确率评测。规则结果、解析回放、隔离合成界面验证与真实云端历史报告分开记录，源码交付不附带业务PDF/解析包/数据库/密钥。
