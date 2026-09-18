# Fixture 来源

`*.synthetic.json` 和测试代码中生成的数据均为合成软件测试数据，不是真实国标或真实 API 响应。
真实 MinerU 解析包、Dify 请求与脱敏响应写入被 Git 忽略的 `data/`，经确认脱敏后才能选入本目录。
Knowledge API 和 Workflow 节点必须分别保存 fixture；未采集真实响应时不能宣称契约联调通过。
