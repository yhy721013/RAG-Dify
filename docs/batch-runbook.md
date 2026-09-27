# 门户批处理入口（人工模式与显式自动模式）

用户已授权自动模式。`auto` 子命令可以不经过逐条人工批准，自动完成上传、解析等待、规则检查、索引、检索回查和发布；后端请求显式携带 `mode=automated`。原 `ingest/preview/publish/status` 保持兼容，默认人工模式。无需新增前端页面，也不直接修改 SQLite 状态。

## 自动模式：一批一份清单，同一知识库累计发布

更新代码后先在服务空闲时正常停止并重新启动门户、证据服务和 worker，确保三个进程均加载新代码，使用项目 `deploy/stop-portal.ps1`、`deploy/start-portal.ps1`。Dify 知识库、嵌入模型等使用门户已应用配置；脚本不会创建或切换知识库。

在 PowerShell 7、项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch auto --input-dir 'D:\标准资料\第一批' --manifest data/batch/batch-001/manifest.json
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch status --manifest data/batch/batch-001/manifest.json
```

后续不同文件使用新的批次清单，仍发布到同一个已配置知识库：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch auto --input-dir 'D:\标准资料\第二批' --manifest data/batch/batch-002/manifest.json
```

新标准与当前版本中的其他标准合并；相同标准号与版本对应的条款集合属于替换，不是盲目追加。遇到替换提示，先查看该批次 `automated-preview.json` 中的 `replacement_details`、`excluded` 和 `blockers`。决定替换后，对同一命令添加 `--confirm-replacements`。条款减少也属于替换。相同 PDF 按 SHA-256 复用上传记录；累计内容未变化时返回 `unchanged`，不建立新索引。

一份清单对应一次发布：提交发布后重新执行 `auto` 只查询/等待原任务，不会扫描新文件。新增文件必须使用另一份清单。一个清单只允许一个客户端进程使用。每批最多100份文档；当前自动回查最多100题，累计最多100个标准，每个标准至少抽取一个条款，其余预算补充其他条款。这是原型限制，不是经过压测的容量承诺。

规则从解析内容预填标准号、名称、版本和范围。无法识别时，错误给出 `document_id` 与 `missing` 字段；上传和解析结果保留。可准备 UTF-8 JSON：

```json
{
  "从manifest.json复制的document_id或sha256": {
    "standard_code": "从实际PDF填写标准号",
    "standard_name": "从实际PDF填写标准名称",
    "edition": "从实际PDF填写版本",
    "scope": "从实际PDF填写适用范围"
  }
}
```

再次运行原 `auto` 命令并添加 `--metadata data/batch/batch-001/metadata.json`。无需到网页填写，但不能凭空推测身份或现行状态。自动模式不会填写虚构复核人或状态核验日期，不把发布日期当成现行状态。已有人工批准条款不能通过这份文件改写身份。

自动检查及输出：

- 原文档与复核记录不变；机器结果进入新快照和发布任务，不覆盖人工批准历史。
- 可识别的父条款、范围和正文引用会自动加入依赖。规则疑点、未知边界、重复编号、缺页、疑似空页、来源损坏、缺失资产、未确认图表、跨页或人工拆分后未确认的边界等阻止相关条款进入集合。排除原因记录在 `excluded`。依赖缺失或循环的机器条款及其传递依赖者继续排除，不删除依赖边；继承历史条款、人工批准条款或重复身份的阻塞仍阻止发布。
- 疑似空页只在原 PDF 页无批注、解析无块、内容流仅含不绘制的状态/坐标/颜色操作时，记录为机器确认空白页；有文字、图像或绘制操作、来源异常及无法读取时仍阻止。不能仅凭 OCR 返回空文本放行。
- 默认发布通过检查的子集，不承诺整份 PDF 全部入库；查阅 `automated-preview.json` 和任务结果中的排除清单。全部不通过则不发布。
- 机器条款保存为 `content_review_status=machine_checked`、`boundary_status=machine_checked`、`evidence_complete=false`；人工复核人/日期为空，保留原问题和 `human_review_required`。
- 原文片段回查标记 `evaluation_kind=automated_smoke`、`human_annotated=false`，不是人工业务问题评测。仍验证版本过滤、索引分块、引用映射和至少90%的 Top-5 回查命中率；失败不切换当前版本。
- 证据带“未经人工复核”说明，报告标记 `knowledge_review_status=human_review_required`。机器证据保持不完整，不能直接用于 `evidence_supported_risk`，现有校验仍要求待确认或证据不足。

同一 Dify 知识库保留不同知识版本的文档，查询依赖 `rag_snapshot_id` 过滤。每次累计发布会为新版本索引完整条款集合，可能重复占用远程文档/向量额度；此改造没有自动清理历史版本。不要在 Dify 手工混入未登记文档或删除历史分区，否则映射核对会阻止发布。

网络失败、等待超时不撤销已排队任务。清单在发出发布请求前保存意图；响应丢失且没有 job_id 时必须用任务页或 `status` 对账，不自动重发。已有 job_id 时重复 `auto` 等待原任务；失败任务通过现有恢复功能重试。`--timeout` 默认每任务14400秒，`--recursive` 扫描子目录。

## 原人工模式

先用 PowerShell 7 启动门户和 worker。以下命令都在项目根目录执行，使用本目录 `.venv`；MinerU 仍由 worker 调用独立 `.venv-mineru`。

```powershell
pwsh -NoProfile -File .\deploy\start-portal.ps1
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch ingest --input-dir 'D:\标准资料' --manifest data/batch/first/manifest.json
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch status --manifest data/batch/first/manifest.json
```

`ingest` 顺序上传 PDF、按内容哈希去重、等待解析并导出 `文档ID.review.json`（含业务正文，不能提交 Git）。可加 `--recursive` 处理子目录。`--timeout` 是每个任务的等待秒数，默认14400。超时只停止客户端等待，不取消后台任务。单文件失败不阻止后续文件，任何文件未完成时退出码为2。

使用相同清单重新运行可继续，已取得文档 ID 的文件不重新上传，已失败任务不会自动重试。上传响应丢失后再次上传由服务器按文件哈希去重。清单绑定本机 origin；不要将清单用于另一台电脑或重建后的实例。一个清单同一时间只由一个脚本进程使用。

条款仍须按现有流程批准。全部资料不必都批准，必要依赖必须完整。满足条件后可通过脚本导出预览：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch preview --manifest data/batch/first/manifest.json --output data/batch/first/preview.json
```

将实际人工核对的问题保存为 UTF-8 JSON 数组，例如：

```json
[
  {
    "case_id": "manual_1",
    "query": "根据本次已批准原文填写的检索问题",
    "expected_clause_uids": ["从预览取得的真实条款UID"],
    "answerable": true
  }
]
```

也可以复制预览中的 `case_draft.cases` 后逐题核对和修订。执行 publish 表示操作者已经完成对传入问题的核对，不得把机器草稿原样传入并冒称人工标注。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m app.portal.batch publish --manifest data/batch/first/manifest.json --preview data/batch/first/preview.json --cases data/batch/first/cases.json --actor '实际复核人'
```

同标准版本替换只有在核对预览后才添加 `--confirm-replacements`。发布接口保留诊断、预览哈希、依赖和检索门禁。该命令会调用真实 Dify 索引及嵌入服务，可能产生费用。

清单在发出发布请求前记录意图，响应丢失时不自动重发。`status` 查询原任务；若发布意图没有任务 ID，须在任务页对账，不能删清单盲目重发。即便接口明确拒绝，当前客户端也保守保留意图，修复后应先核对，再创建新的批次清单。失败或中断任务沿用现有任务恢复功能。

客户端自动获取本机会话 Cookie 和 CSRF token；重启后重新运行命令获取新会话。拒绝远程门户地址，不读取或输出 Dify 密钥。程序不直接连接 SQLite，不伪造人工批准，也不管理服务进程。
