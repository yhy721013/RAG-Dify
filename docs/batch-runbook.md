# 门户批处理入口（保留现有审核门禁）

当前交付只完成命令行操作层；**免人工审核的自动入库后端模式尚未实现**。新增模式的 schema 修改被自动审批检查阻止，原人工批准、完整性与发布校验保持原样。不支持此前讨论的 `--mode automated`，也没有新增前端页面。

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

客户端自动获取本机会话 Cookie 和 CSRF token；重启后重新运行命令获取新会话。拒绝远程门户地址，不读取或输出 Dify 密钥。程序不直接连接 SQLite，不绕过审批、不自动修改条款，也不管理服务进程。
