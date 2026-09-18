# 检索标注

`retrieval_cases.jsonl` 有意留空，等待人工根据批准快照填写，禁止虚构真实命中率。
每行字段：`case_id`、`snapshot_id`、`query`（1～250 字）、`expected_clause_uids`、`answerable`、`annotated_by`、`annotated_at`。
UID 使用 import-reviewed 导入后确定的条款身份；无答案问题的 expected_clause_uids 必须为空。
评测按 Top-5 分块映射为条款后去重计分，同时记录多目标覆盖、无答案候选率和技术失败。
少量冒烟问题不等于指南阶段 E 的完整业务验收集，也不能证明安全评估准确率。
