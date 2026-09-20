# Windows 开发者预览版的开发与源码交付

接手入口是 [README](README.md) 的两条路径和 [门户线性运行手册](docs/portal-runbook.md)，首次实操参考 [首测示例](docs/first-test.md)。仓库不附带历史试点资料；旧入口仅供维护，见 [历史版本与底层接口](docs/legacy-stage-d.md)。

先阅读根目录架构指南、AGENTS.md、docs/portal-plan.md、docs/portal-runbook.md 和最新验收记录。用户已明确授权本地前端扩展；不要据此扩展设备类别、自动批准条款或开展阶段 E 业务结论。

PowerShell 7 / Python 3.12，测试使用工作区 `.venv`，MinerU 使用 `.venv-mineru`。修改前先读相关文件；保持四个证据接口、条款身份、不可变快照和待复核报告契约。新增第三方行为须核查官方文档/固定源码，并在可用时加入脱敏真实响应 fixture。

```powershell
git switch -c codex/your-change
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
git diff --check
```

按功能提交、更新 docs/acceptance.md；区分单元模拟、真实解析、真实索引和真实模型报告。不要在测试中访问个人 Dify 环境。真实联调使用自己的专用数据根目录、知识库、Workflow 与密钥。

接手时先从无配置的源码包初始化，并走页面五步向导。排错交付“复现操作 + Git 提交 + 任务 ID + 脱敏诊断 ZIP”，不要提交配置或原始 SSE。共享的诊断实现位于 `app/portal/diagnostics.py`，配置草稿/应用在 `setup.py` / `services.py`，控制任务与业务 worker 的生命周期分开；继续修改时保留这一约束。输入契约真实夹具位于 `fixtures/dify_portal/workflow_parameters.real.json`，来源为本轮已发布专用应用 Service API；夹具不含凭据，不能替代目标开发者自己的实际诊断。

本轮只准备本地版本化源码与干净 ZIP，不创建/推送远程。接收ZIP可直接初始化测试；需要提交开发改动时再初始化自己的Git仓库或使用获授权的仓库克隆。后续分享或公开发布前逐项检查：

1. 明确仓库地址和接收开发者，再审计 **HEAD 与完整历史** 的密钥和数据。发现曾提交凭据须先轮换并处理历史；`.gitignore` 不会清理旧提交。
2. 选择已验收提交，附 uv.lock、MinerU 锁文件、无密钥配置模板、Workflow 生成器、API/运行手册和验收限制。
3. 每位开发者自建 Dify app/dataset，配置自己的模型和 HTTPS 证据地址。不要通过聊天、提交或源码包分发 API Key。
4. 不分发业务 PDF、解析包、数据库、报告、权重或虚拟环境。公开测试照片只交付来源与许可记录，下载和使用遵循原许可。标准文件由使用者合法获取。
5. 当前未指定开源许可证；私有交付不意味着允许公开再分发。若将来公开源码，先由项目所有者决定许可证及第三方资料授权。

发布说明应注明“Windows 开发者预览版”、源码提交与ZIP SHA-256、测试环境和结果、是否重新运行了真实Dify流程、六项检查范围及剩余限制。只从干净HEAD导出；接收者按README验证，不能依赖开发机的 `data/`。公开模板的HTTPS、dataset和snapshot绑定保持占位值；历史Git对象仍可能包含旧实例标识，当前模板去绑定不等于重写了历史。发布公开Git仓库前单独审查历史，不能只检查ZIP。

回滚以 Git 代码提交为单位。新前端数据目录与旧试点隔离；备份 `.env.portal`、data/portal 与原始资料后再升级。不要用覆盖数据库的方式回滚已保存证据或报告。历史索引版本暂不自动清理。

批量上传队列另有纯JavaScript状态/拖放事件回归 `tests/js/test_upload_queue.cjs`，由pytest在检测到Node时调用；没有Node时会明确跳过这一项，门户运行和Python接口测试不依赖Node。修改上传前端时应安装可用Node并运行该测试，或执行内置浏览器验证；不要把事件模拟称为操作系统文件管理器真实拖拽验证。
