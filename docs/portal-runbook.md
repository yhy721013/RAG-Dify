# 门户运行手册 · 从空源码目录到首份报告

这是 Windows 开发者预览版的推荐运行路径。准备清单和数据传输边界见 [README](../README.md)。首次运行按下列顺序完成一次；页面启动后，配置变化使用“应用草稿”，不要重复启动。

## 1. 初始化并启动一次

在解压后的项目根目录，用 PowerShell 7 执行：

```powershell
pwsh --version
py -3.12 --version
pwsh -File deploy/init-portal.ps1 -InstallMinerU
pwsh -File deploy/start-portal.ps1
```

预期：创建本目录 `.venv` 与独立 `.venv-mineru`，按锁文件安装依赖，生成 `.env.portal` 和空数据，然后提示 `http://127.0.0.1:8001` 可打开。没有云端密钥时也能打开向导；尚未发布知识版本时证据服务 `/health` 返回 `503 not_ready` 属预期。

失败入口：终端错误 → `data/portal-runtime/startup-bootstrap.html` →（Python 已运行时）`startup-diagnostics.html` / 服务日志。原文件不存在时说明尚未走到对应启动阶段。第一次解析需下载模型资源，硬件和网络问题看解析日志，不用全局 Python 或 pytest 替代项目环境。

`init` 不覆盖已有 `.env.portal`。若已按 README 路径 A 初始化，带 `-InstallMinerU` 再运行只补齐环境；若服务已运行，跳过启动命令。门户固定8001、独立证据服务8002，都监听127.0.0.1；旧8000试点不参与本流程。

## 2. 向导：本机环境

打开“00 首次配置与诊断 → 1 本机环境”。默认 MinerU 路径为 `.venv-mineru/Scripts/mineru-kit.exe`；也可选择已验证的独立 MinerU 环境。文件限额默认为50 MiB/300页，解析超时7200秒。

页面配置的通用操作是：填写 → **保存配置草稿** → **应用草稿并重启后台服务** → **检查已应用配置**。草稿写入 `.env.portal.draft`，应用前不改变运行配置；应用时只重启证据服务和worker，门户与其托管隧道保持运行。只有任务空闲时可应用。外部文件修改会触发冲突，环境变量覆盖项不能从页面覆盖。

密码框留空保留已有密钥，保存后清空且不回显。新生成的证据密钥在保存前复制并妥善暂存，步骤4用于Dify Secret；也可由本人从本机 `.env.portal` 取值，勿把它发到聊天、Git或诊断附件。若重新生成替换密钥，应用后必须同步Dify并发布。

成功标志：解析器版本、两份数据库和worker心跳诊断通过。此时云端项仍未配置是正常的。失败看“查看本机服务日志”。

## 3. 向导：专用知识库

1. 打开 [Dify 知识库](https://cloud.dify.ai/datasets)，创建**空白专用知识库**。不要复用别人的试点库或含未知文档的库。
2. 在Dify配置可用的嵌入模型。默认适配提供方 `langgenius/siliconflow/siliconflow`、模型 `Qwen/Qwen3-Embedding-4B`；模型凭据只在Dify管理。
3. 创建只授权该库的Knowledge API Key。在向导“2 专用知识库”填写Service API地址（Cloud通常为 `https://api.dify.ai/v1`）、库ID或库页面网址、密钥、嵌入提供方和模型ID，保存并应用。
4. 点击“初始化空白专用知识库”，等待任务成功。已有资料时此操作拒绝修改。

成功标志：知识库真实鉴权、模型配置、`rag_snapshot_id`字符串元数据及文档归属检查通过。初始化设置High Quality、Hybrid Search、语义/关键词各0.5、Top-5。失败看该任务诊断；401检查密钥，403检查库授权及模型权限。

每个实例的数据目录、知识库和工作流独立。已有发布版本时禁止直接换库；新开发者应在自己的源码目录初始化，不能只复制另一实例的API Key或远端文档。

## 4. 向导：HTTPS 与 Dify 工作流

### 4.1 给8002建立HTTPS入口

使用自有HTTPS时，将其仅转发到 `127.0.0.1:8002`。使用Quick Tunnel时：

1. 从向导“3 HTTPS入口 → 安装指定版本工具”下载官方cloudflared 2026.9.1 Windows x64；保存到环境步骤显示的路径，默认 `data/tools/cloudflared/2026.9.1/cloudflared.exe`。启动会验证固定SHA-256。
2. 确认证据密钥已配置，点击“启动本实例隧道”。出现连接状态和新地址后，点“填入新地址”，保存并应用。
3. 在“5 检查与首测”检查本机和HTTPS证据服务鉴权。进程显示已连接不代替HTTPS检查。

失败入口：隧道任务诊断/服务日志。检测到用户已有 `.cloudflared/config.yml` 或 `config.yaml` 时不会覆盖它，应使用自有HTTPS或独立环境。页面只管理 `data/portal-runtime/managed-tunnel.json` 登记的进程，不接管其他隧道。8001上传和复核页面不接公网。

### 4.2 导入专用门户Workflow并启用API

1. 在Dify配置可用的视觉/评估模型。默认提供方 `langgenius/siliconflow/siliconflow`，模型 `Qwen/Qwen3.5-27B`，两个LLM节点都使用它且 `enable_thinking=false`。向导模型字段需与Dify实际设置一致；更换模型后重新验收。
2. 在向导“4 Dify工作流”保存并应用模型字段，点击**下载当前已应用配置的DSL**，导入一个新的专用Workflow。它带有自己的知识库、HTTPS和模型绑定，Secret为空。
3. 核对原生检索节点的知识库，两个LLM节点图片变量均为 `start.images`，检索按 `rag_snapshot_id = start.snapshot_id` 过滤。切换模型后再核对图片绑定。
4. 发布服务API并停用公开Web App。若Dify在首次发布前不能关闭Web App：**保持证据Secret为空、尚无已发布知识版本 → 首次发布 → 立即停用Web App → 填入证据Secret → 再发布更新**。每次发布后都复查Web App停用、后端API启用。
5. 在该应用环境变量中设置 `EVIDENCE_API_BASE_URL` 为本实例HTTPS地址，`EVIDENCE_API_TOKEN` Secret为本机同值。创建该应用自己的Workflow API Key，填回门户；可粘贴编排页面网址作为应用ID，保存并应用。
6. 回到向导，逐项记录已核对的人工确认，运行“检查已应用配置”。

成功标志：Workflow鉴权和**已发布**输入契约通过。Knowledge Key与Workflow Key不能互换；后者在本轮Cloud实例中以 `app-` 开头，实际鉴权结果才是依据。缺失权限、Secret未绑定、模型被停用等问题要根据失败项修复。

门户Workflow保留七个输入：`images`、`equipment_type`、`equipment_description`、`operating_state`、`work_context`、`same_equipment_confirmed`、`snapshot_id`。最后一项由本机后端固定，设备评估页面不要求手工填写。**不要给门户导入旧版 `safety-assessment.yml`**，它是六输入的历史单快照结构。

## 5. 上传、复核并发布第一版

跟随 [首次测试示例](first-test.md) 准备自己的PDF和标注：

1. 上传完整、未加密的国家标准PDF。系统验证大小/页数并按SHA-256归档；同文件复用既有任务。后台固定 `--pages all --format zip --tier standard --ocr-mode auto`，不启用远程解析。
2. 解析任务完成后进入“对照复核”，确认完整页覆盖。填写标准号、完整名称、版本、适用范围、状态、核验日期和可核查来源；输入真实复核人。
3. 按条款筛选/搜索，对照原页检查原文、数值、单位、否定词、来源块、跨页、图表及必要上下文。依赖选择器显示条款号和摘要，UID由系统处理。修改先保存，再逐项确认并批准；机器候选不会自动批准。
4. 勾选标准，预览已批准且依赖闭合的集合。未知边界、缺失资产、重复身份、未批准依赖等问题必须先处理。同标准/版本会整体替换该标准的旧集合，页面列出替换明细并要求确认。
5. 用表单填写检索问题并勾选预期条款，填写复核人，执行“建立索引、自检并发布”。至少一道可回答题；可另加无答案题，高级JSON仅供已有标签导入。

成功标志：索引、分块、元数据和映射回读一致，检索Top-5命中率≥0.9且没有技术错误，发布任务成功，页面出现当前知识版本。无答案题可能仍有相似候选，不能将此解释为有正确答案。

失败入口：发布预览阻塞项或该任务“诊断与日志”的检索明细。不得为通过门禁随意改变预期答案。编辑已批准原文或依赖会撤销相关批准；未知边界和缺失资产不会自动补齐。内容完全未变时不重复发布。

## 6. 图片、工况与报告

按[示例](first-test.md#图片和工况示例)选取1～4张同设备JPEG/PNG（每张≤5MiB），检查预览顺序，填写工况；不知道的状态写“未知”，确认同设备后提交。只有已发布版本才能评估，提交时后端冻结该版本，不随后续发布改变。

成功标志：任务成功，页面展示待专业人员复核的六项检查、适用条件、证据和待确认事项；可下载Markdown/JSON。只有Workflow输出report_id且本机HTTP/SQLite回读、请求/图片顺序/版本一致时才展示报告。

失败入口：该评估任务的诊断、失败节点与运行ID；不会以旧报告冒充本次结果。记录真实运行，不把测试夹具或仅HTTP200当成完整报告验收。原图会参与两个模型节点，参考README的数据去向后选择适合上传的材料。

## 诊断与排错

| 检查或现象 | 说明与处理 |
|---|---|
| 只读诊断 | 验证解析器、数据库、worker、知识库鉴权/模型/元数据/归属、Workflow `/info`和`/parameters`、本机/HTTPS鉴权；不调用模型或写业务证据 |
| 人工确认 | API不能证明Dify内部Secret和所有图绑定正确；须在Dify逐项核对，页面单独记录其来源 |
| 真实链路项待验证 | 首份报告成功保存并回读后才通过；云端配置以后变化仍需重新实测 |
| 配置结果过期 | 按配置指纹标记stale，重新诊断；草稿轮换证据密钥时鉴权须应用后再测 |
| 401 / 403 / 429 | 对应密钥、权限/模型可用性、限流/额度；按详情及Retry-After处理，不连续新建评估 |
| TLS / 隧道失败 | 核对进程、地址及网络；临时地址变化后同步本机和Dify并发布，不关闭TLS验证 |
| 解析失败 | 查看任务中的有限parser.log；核对独立环境、资源和完整PDF，修复后恢复原任务 |
| 远端文档归属错误 | 对照本地同步清单与远端文档，不自动删除未知文档或绕过映射 |

“查看诊断与日志”提供阶段、错误代码、字段、请求/运行ID、有限节点事件与日志；可刷新并下载脱敏ZIP。ZIP不收录配置密钥、PDF、图片、数据库、报告正文和原始模型输入输出。分享排错材料时提供该ZIP、源码提交及复现步骤。

## 停止与恢复

任务结束后运行：

```powershell
pwsh -File deploy/stop-portal.ps1 -WhatIf
pwsh -File deploy/stop-portal.ps1
```

脚本核对PID及创建时间，默认拒绝中断运行任务；关闭页面不停止服务。确需中断时管理员可使用 `-Force`，下次启动会标记未完成任务，先查状态再恢复。

已停止后，重新执行第1步中的**启动命令一次**。完整停止会结束门户托管隧道，需要重新建立临时地址，并在本机/Dify两侧更新和发布。配置应用只重启worker/证据服务，会保留该隧道。

评估已取得运行ID时恢复只对账原运行；已提交但未取得ID时需在Dify日志人工核对，禁止自动重复提交。索引创建响应丢失时依据确定性文档名和本机 `data/portal/manifests` 对账，不删除清单盲目重跑。解析进程或同步锁异常残留时，先核对所属进程和任务，再处理具体残留，不覆盖数据库。

## 命令行对照与开发资料

以下是页面动作的**替代入口**，不属于首次流程中需要重复执行的步骤：

| 用途 | 项目根目录命令 |
|---|---|
| 实际只读诊断 | `pwsh -File deploy/doctor-portal.ps1` |
| 初始化空白专用库 | `.\.venv\Scripts\python.exe -X utf8 -m app.portal.cli configure-empty-dataset` |
| 按本机配置生成门户DSL | `.\.venv\Scripts\python.exe -X utf8 -m workflows.build_portal`；输出到运行时生成的 `data/portal/workflows/portal.candidate.yml` |
| 代码测试 | `.\.venv\Scripts\python.exe -X utf8 -m pytest -q` |
| 导出源码 | 干净Git工作区执行 `pwsh -File deploy/export-source.ps1` |

仓库 [门户结构模板](../workflows/portal.template.yml) 不含实例绑定，用于源码阅读；CLI或页面才生成当前环境候选。模型/嵌入参数默认读取本机配置；详细接口见 [Portal API](portal-api.md)，协作与发布要求见 [CONTRIBUTING](../CONTRIBUTING.md)。文中所有 `data/` 路径均由运行产生，不是源码包预置资产。

项目只面向可信本地用户。已有真实技术验证及未验证范围见 [验收记录](acceptance.md)，依赖/云实例参考版本见 [版本基线](versions.md)。
