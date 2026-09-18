# Fixture 来源

`*.synthetic.json` 和测试代码中生成的数据均为合成软件测试数据，不是真实国标或真实 API 响应。
真实 MinerU 解析包、Dify 请求与脱敏响应写入被 Git 忽略的 `data/`，经确认脱敏后才能选入本目录。
Knowledge API 和 Workflow 节点必须分别保存 fixture；未采集真实响应时不能宣称契约联调通过。

`mineru_4_0_2.blank-page.real.json` 是从 sample_6 的真实 middle_json.json 中原样摘出的零基页 3，无原文内容。来源 PDF SHA-256：f9aae99d9b9ffe37130170a607014d437baa91f14a25ea1ac7ee2d71654709b3；MinerU 4.0.2 standard；2026-09-18 本地解析。此页省略 blocks，已对照原 PDF 确认空白。

Dify 两类 synthetic fixture 的结构依据固定 tag 1.17.1 的 Service API 与 `api/core/workflow/nodes/knowledge_retrieval/retrieval.py` 核查；合成 fixture 本身不能作为真实联调证据。

`dify_cloud/*.real.json` 是 2026-09-18 本轮 Dify Cloud Service API 的 9 份真实脱敏捕获：知识库详情、创建文档、文档列表、索引完成、4 页分块响应和检索响应。
业务文本／文档名称已替换，UUID 一致映射，人员字段已脱敏；请求和响应的核心字段、枚举、分页及集合形状保留。来源文件哈希和捕获时间见 dify_cloud/provenance.json。
这些 fixture 用于第三方响应结构回归；原文和分块全文的一一校验依赖本地 data/ 中的实际回读，不能用已删去业务文字的 fixture 代替。
`dify_workflow_retrieval.real.json` 来自阶段 D 已导入草稿中原生 Knowledge Retrieval 的单步运行：界面显示 SUCCESS、2.542s、开始时间2026-09-18 17:45:03。通过输出编辑器复制完整JSON后，去除标准文字、名称并一致替换UUID；保留5条结果和原生metadata结构。实际命中全部映射回本地条款，首条为5.3.7；本地复查记录见data/workflows/native-retrieval-check.json。这不代表工作流端到端已经通过。

`workflow_input.synthetic.json` 是两张图片元数据与视觉输出的合成结构用例。File.to_dict字段根据固定参考版本 graphon 0.7.0 核查；它不是实拍图片或真实视觉模型输出。
