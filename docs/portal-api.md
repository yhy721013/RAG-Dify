# 本地测试台接口

本文件只描述本项目新入口。原证据服务四个接口不变，继续参照指南和 `config/*.schema.json`。

Portal 仅监听 127.0.0.1:8001。GET `/api/status` 建立 SameSite=Strict、HttpOnly 本机会话，并返回 `csrf_token`；写请求必须携带同一来源 Origin、会话 Cookie 和 `X-CSRF-Token`，浏览器不保存 Dify 或证据密钥。不接受外部 Host。CSRF token 随服务重启变更，页面刷新后重新获取。

| 方法 / 路径 | 请求 / 响应 |
|---|---|
| GET /api/status | 配置是否齐备、worker 心跳、当前版本、上传限制；不返回服务密钥 |
| POST /api/documents | multipart `file`；返回 document_id、页数、状态、是否复用 |
| GET /api/documents | 文件、页数、批准/候选计数、状态 |
| GET /api/documents/{id} | 完整待复核记录、normalized 来源、revision 与图表链接 |
| GET /api/documents/{id}/pdf | 归档原 PDF |
| GET /api/documents/{id}/pages/{number} | 从 1 开始的原 PDF PNG 页预览；不修改原文件 |
| GET /api/documents/{id}/assets/{asset_id} | 登记过的资产；不接受任意文件路径 |
| POST /api/documents/{id}/metadata | revision、actor、metadata（七个标准元数据字段） |
| POST /api/documents/{id}/candidates/{candidate_id}/edit | revision、actor、changes、block_ids |
| POST …/approve | revision、actor、acknowledgements，须含 text/boundary/context/assets/scope |
| POST …/split | revision、actor、offset；按已保存文本偏移拆分，之后重新复核 |
| POST …/merge | revision、actor、candidate_ids；按指定顺序合并，保留来源 |
| POST /api/releases/preview | document_ids；返回基础版本、替换集合、待复核数、批准子集、preview_hash |
| POST /api/releases | 同一 document_ids、preview_hash、confirm_replacements、actor、cases；返回发布任务 |
| GET /api/releases | 当前版本指针及全部已发布版本 |
| POST /api/assessments | multipart images（1～4）、equipment_description、operating_state、work_context、same_equipment_confirmed、submission_id |
| GET /api/jobs / GET /api/jobs/{id} | 有限任务状态、阶段、结果 ID、脱敏错误，不返回原始 SSE |
| POST /api/jobs/{id}/retry | 仅失败/中断任务恢复；歧义运行禁止重发 |
| GET /api/jobs/{id}/report | 仅成功评估任务对应的保存报告 |
| GET /api/jobs/{id}/report/md 或 /json | 导出已保存报告 |

`revision` 是整个文档的乐观锁。过期编辑返回 409；任何内容修改均重新待复核，审核记录在独立任务库保存前后版本。`submission_id` 在一次用户提交期间保持不变，避免浏览器重试创建重复任务；不同内容复用相同 ID 返回冲突。

任务状态：queued → running → succeeded / failed / needs_attention；进程恢复将遗留 running 标记为 interrupted。发布任务冻结当时已批准条款和自检标签。评估任务固定提交时版本，后台不自动换到更新版本。

`portal.db` 的 documents/jobs/releases/state/review_audit/job_events 与 `evidence.db` 五张业务表分离。GET 单个任务额外返回阶段历史 events；恢复任务不删除既有错误记录，历史中不包含原始 SSE 或密钥。PDF、解析及导出保存在配置的数据根目录。门户证据服务只接受同时在 releases 登记且证据库 active 的知识版本；旧服务继续使用单一 ACTIVE_SNAPSHOT_ID。
