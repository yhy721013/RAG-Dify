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
