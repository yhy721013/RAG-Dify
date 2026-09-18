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
| MinerU 档位 | standard 实测扫描样本 10 页；flash txt 实测文本层样本 34+36 页 |
| Dify 环境 | 用户配置的 Dify Cloud Service API，2026-09-18 完成阶段 C 真实联调 |
| Dify tag | 1.17.1 为适配源码参考；不声称云实例运行该 tag |
| Dify 参考源码 commit | tag 1.17.1 → 8387590ace4a094de812b7847fc6a4c3a27cd52b（git ls-remote 核查） |
| Dify 实例 commit / 容器镜像 | 云服务托管，当前 Knowledge API 未暴露；本项目未部署 Dify 容器 |
| 嵌入提供方 / 插件版本 | langgenius/siliconflow/siliconflow；版本未由已授权接口暴露 |
| 嵌入模型 ID / 实际维度 | Qwen/Qwen3-Embedding-4B；维度未由知识库详情返回，不能把模型默认值写成实测 |
| Workspace 模型详情查询 | 返回403：当前 dataset scoped key 无此接口授权；未申请扩大密钥权限 |
| 多模态模型 ID | 未配置（阶段 D） |
| Workflow DSL 版本 | 未创建，阶段 D，不生成未经验证的 YAML |
| 业务知识快照 | pilot_20260918_01，GB/T 8196-2018 的10条人工批准记录，已激活 |
| Dify dataset ID | 实际值保存在本地 .env 和 data/manifests/sync_*.json |
| Dify document ID | 实际值保存在本地同步清单；1个文档、10个分块，重复同步保持不变 |
| 检索设置 | General / High Quality / Hybrid Search，语义与关键词0.5/0.5，Top-5，阈值关闭，无独立重排模型 |
| 业务快照内容哈希 | 9bb6ae7e29e24ac7891ba04b51cbb400cd612f8d3716a725f19639cb24ba2afc |
| 实际映射哈希 | ff565e78dcee594f578dd59b0d8776cb462407436cf7b6917751a5742b5b7e43 |

接口核查依据：[MinerU 输出契约](https://opendatalab.github.io/MinerU/reference/output_files/)、[MinerU Quick Start](https://opendatalab.github.io/MinerU/quick_start/)、[Dify 创建文档](https://docs.dify.ai/en/api-reference/documents/create-document-by-text)、[Dify 分块分页](https://docs.dify.ai/en/api-reference/chunks/list-chunks)。文档核查不能替代真实实例验证。

本轮可复验依据为应用 Git 提交、uv.lock、原 PDF 与批准条款哈希、不可变业务快照、实际索引映射以及 fixtures/dify_cloud/provenance.json。云平台更新不受本项目锁文件控制；切换自建部署时需补齐实例 tag/commit、镜像 digest 和模型插件版本，并重新跑真实契约验收。
