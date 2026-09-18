# Fixture 来源

`*.synthetic.json` 和测试代码中生成的数据均为合成软件测试数据，不是真实国标或真实 API 响应。
真实 MinerU 解析包、Dify 请求与脱敏响应写入被 Git 忽略的 `data/`，经确认脱敏后才能选入本目录。
Knowledge API 和 Workflow 节点必须分别保存 fixture；未采集真实响应时不能宣称契约联调通过。

`mineru_4_0_2.blank-page.real.json` 是从 sample_6 的真实 middle_json.json 中原样摘出的零基页 3，无原文内容。来源 PDF SHA-256：f9aae99d9b9ffe37130170a607014d437baa91f14a25ea1ac7ee2d71654709b3；MinerU 4.0.2 standard；2026-09-18 本地解析。此页省略 blocks，已对照原 PDF 确认空白。

Dify 两类 synthetic fixture 的结构依据固定 tag 1.17.1 的 Service API 与 `api/core/workflow/nodes/knowledge_retrieval/retrieval.py` 核查；尚无真实 Dify fixture，不能作为真实联调证据。
