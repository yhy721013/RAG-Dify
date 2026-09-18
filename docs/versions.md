# 版本与实际运行基线

记录日期：2026-09-18。依赖精确版本见 `uv.lock`。

| 项目 | 实测或状态 |
|---|---|
| PowerShell | 7.6.0 |
| Python | 3.12.6，本地 `.venv` |
| uv | 0.12.16 |
| FastAPI / Pydantic | 0.141.1 / 2.13.5 |
| SQLite schema_version | 1，五张业务表 |
| MinerU | 4.0.2，独立 `.venv-mineru` |
| DocVortex | 0.4.12 |
| MinerU 档位 | standard 待冒烟；flash txt 仅用于有文本层的样本 |
| Dify tag | 指南参考 1.17.1，未部署／未完成实例验证 |
| Dify commit / 容器镜像 | 待实际环境记录，不使用 latest |
| 模型插件 / 多模态模型 ID | 未配置（阶段 D） |
| 嵌入模型 ID / 维度 | 未配置 |
| Workflow DSL 版本 | 未创建，阶段 D，不生成未经验证的 YAML |
| 业务知识快照 | 未发布；demo_snapshot 仅在测试临时目录 |

接口核查依据：[MinerU 输出契约](https://opendatalab.github.io/MinerU/reference/output_files/)、[MinerU Quick Start](https://opendatalab.github.io/MinerU/quick_start/)、[Dify 创建文档](https://docs.dify.ai/en/api-reference/documents/create-document-by-text)、[Dify 分块分页](https://docs.dify.ai/en/api-reference/chunks/list-chunks)。文档核查不能替代真实实例验证。
