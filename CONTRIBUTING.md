# 开发与私有源码交付

先阅读根目录架构指南、AGENTS.md、docs/portal-plan.md、docs/portal-runbook.md 和最新验收记录。用户已明确授权本地前端扩展；不要据此扩展设备类别、自动批准条款或开展阶段 E 业务结论。

PowerShell 7 / Python 3.12，测试使用工作区 `.venv`，MinerU 使用 `.venv-mineru`。修改前先读相关文件；保持四个证据接口、条款身份、不可变快照和待复核报告契约。新增第三方行为须核查官方文档/固定源码，并在可用时加入脱敏真实响应 fixture。

```powershell
git switch -c codex/your-change
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
```

按功能提交、更新 docs/acceptance.md；区分单元模拟、真实解析、真实索引和真实模型报告。不要在测试中访问个人 Dify 环境。真实联调使用自己的专用数据根目录、知识库、Workflow 与密钥。

本轮只准备本地版本化源码与干净 ZIP，不创建/推送远程。后续交付私有 Git 仓库时：

1. 明确仓库地址和接收开发者，再审计 **HEAD 与完整历史** 的密钥和数据。发现曾提交凭据须先轮换并处理历史；`.gitignore` 不会清理旧提交。
2. 选择已验收提交，附 uv.lock、MinerU 锁文件、无密钥配置模板、Workflow 生成器、API/运行手册和验收限制。
3. 每位开发者自建 Dify app/dataset，配置自己的模型和 HTTPS 证据地址。不要通过聊天、提交或源码包分发 API Key。
4. 不分发业务 PDF、解析包、数据库、报告、权重或虚拟环境。公开测试照片只交付来源与许可记录，下载和使用遵循原许可。标准文件由使用者合法获取。
5. 当前未指定开源许可证；私有交付不意味着允许公开再分发。若将来公开源码，先由项目所有者决定许可证及第三方资料授权。

回滚以 Git 代码提交为单位。新前端数据目录与旧试点隔离；备份 `.env.portal`、data/portal 与原始资料后再升级。不要用覆盖数据库的方式回滚已保存证据或报告。历史索引版本暂不自动清理。
