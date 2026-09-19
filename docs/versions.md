# 版本与实际运行基线

记录日期：2026-09-19。依赖精确版本见 `uv.lock`。

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
| 嵌入提供方 / 插件版本 | langgenius/siliconflow/siliconflow；阶段D工作台实查插件0.0.61 |
| 嵌入模型 ID / 实际维度 | Qwen/Qwen3-Embedding-4B；维度未由知识库详情返回，不能把模型默认值写成实测 |
| Workspace 模型详情查询 | 返回403：当前 dataset scoped key 无此接口授权；未申请扩大密钥权限 |
| 多模态模型 ID | Qwen/Qwen3.5-27B，enable_thinking=false；两个节点已通过真实单图、双图完整流程；原Qwen/Qwen2.5-VL-32B-Instruct返回403 Model disabled |
| Workflow DSL 版本 | 0.7.0；stage-d-v3，19节点；本轮单图／双图完整流程及真实失败输入回放通过，未发布 |
| 正式DSL SHA-256 | e389dcd26e401323e4d6a85c709163158ac0b12dec18a708258e9f008830e8c5，workflows/safety-assessment.yml，无密钥 |
| 临时证据服务入口 | 用户配置的Cloudflare Quick Tunnel；实际地址和进程记录见data/quick_tunnel/runtime.json，Dify端HTTPS健康检查已通过 |
| Dify节点契约参考 | tag 1.17.1 的 graphon==0.7.0；只下载wheel阅读源码，未将其安装到证据服务依赖中 |
| 视觉模型参数参考 | 官方siliconflow插件qwen3.5-27b.yaml，Git blob c5aa85ed1271fef6473bb3e002467d7d237dfcb5；声明vision和enable_thinking，已与云端UI及单步调用核对 |
| 业务知识快照 | pilot_20260918_01，GB/T 8196-2018 的10条人工批准记录，已激活 |
| Dify dataset ID | 实际值保存在本地 .env 和 data/manifests/sync_*.json |
| Dify document ID | 实际值保存在本地同步清单；1个文档、10个分块，重复同步保持不变 |
| 检索设置 | General / High Quality / Hybrid Search，语义与关键词0.5/0.5，Top-5，阈值关闭，无独立重排模型 |
| 业务快照内容哈希 | 9bb6ae7e29e24ac7891ba04b51cbb400cd612f8d3716a725f19639cb24ba2afc |
| 实际映射哈希 | ff565e78dcee594f578dd59b0d8776cb462407436cf7b6917751a5742b5b7e43 |

接口核查依据：[MinerU 输出契约](https://opendatalab.github.io/MinerU/reference/output_files/)、[MinerU Quick Start](https://opendatalab.github.io/MinerU/quick_start/)、[Dify 创建文档](https://docs.dify.ai/en/api-reference/documents/create-document-by-text)、[Dify 分块分页](https://docs.dify.ai/en/api-reference/chunks/list-chunks)。文档核查不能替代真实实例验证。

本轮可复验依据为应用 Git 提交、uv.lock、原 PDF 与批准条款哈希、不可变业务快照、实际索引映射以及 fixtures/dify_cloud/provenance.json。云平台更新不受本项目锁文件控制；切换自建部署时需补齐实例 tag/commit、镜像 digest 和模型插件版本，并重新跑真实契约验收。

模型调整依据：[SiliconFlow服务调整公告](https://docs.siliconflow.cn/docs/release-notes/overview)列出旧视觉模型下线；[官方插件模型声明](https://github.com/langgenius/dify-official-plugins/blob/main/models/siliconflow/models/llm/qwen3.5-27b.yaml)与[Qwen模型卡](https://huggingface.co/Qwen/Qwen3.5-27B)说明新模型的视觉和参数契约。可用性以本项目本轮真实调用为准，不由界面列出模型推断。

## 本地测试台运行基线（2026-09-20）

| 项目 | 本轮实测 |
|---|---|
| 本地入口 | 127.0.0.1:8001；独立证据服务8002；独立单worker |
| 数据目录 | data/portal；portal.db任务/复核/历史与evidence.db五张证据业务表分开 |
| 新增依赖 | python-multipart 0.0.32、Pillow 12.3.0、pypdfium2 5.13.0；精确锁定于uv.lock |
| 页面 | HTML + 原生JavaScript；无需Node构建；编辑时一次性使用Prettier 3.6.2整理格式 |
| MinerU | 4.0.2，all/zip/standard/auto；本轮文本PDF34页、扫描PDF10页完整覆盖 |
| 新Workflow | portal-v1，独立应用；服务API已发布，公开Web App停用；原stage-d-v3应用保持独立 |
| 多模态/嵌入 | 沿用Qwen/Qwen3.5-27B、enable_thinking=false及Qwen/Qwen3-Embedding-4B |
| 版本过滤 | rag_snapshot_id字符串字段，原生检索手动is条件引用start.snapshot_id；Service API条件嵌套于retrieval_model |
| 知识版本 | portal_6bcc6616a6f5feea9fe8868b：4条；portal_6478a1021d2231b9be0b1e2b：10条，当前版本 |
| 真实结果 | 单图117.810s、双图143.535s成功；混设备23.159s在范围门禁拒绝；不作时延/准确率承诺 |
| 临时HTTPS | 专用Quick Tunnel实际地址和进程记录位于data/portal-runtime/tunnel.json；更换地址须重新绑定 |

交付workflows/portal.template.yml为无密钥、无实例绑定模板，workflows/build_portal.py生成本机候选。真实导入运行文件保存在忽略目录；不把模板声称为已绑定其他开发者环境。Dify Cloud的实例commit和容器镜像仍不可由当前接口验证。
