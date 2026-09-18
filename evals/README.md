# 检索标注

`retrieval_cases.jsonl` 已准备首轮15题，基于 pilot_20260918_01 已批准的10条 GB/T 8196-2018 条款：10道单条款题、2道多条款题、3道当前快照无答案题。
这15题由 Codex 初标，用户已明确核对并确认全部预期条款及无答案标注；annotated_by 记录为“Codex 初标；用户（本次对话确认）复核”。尚未执行真实检索，没有命中率结论。
每行字段：`case_id`、`snapshot_id`、`query`（1～250 字）、`expected_clause_uids`、`answerable`、`annotated_by`、`annotated_at`。
UID 使用 import-reviewed 导入后确定的条款身份；无答案问题的 expected_clause_uids 必须为空。
评测按 Top-5 分块映射为条款后去重计分，同时记录多目标覆盖、无答案候选率和技术失败。
少量冒烟问题不等于指南阶段 E 的完整业务验收集，也不能证明安全评估准确率。

可读复核单及逐题依据位于 `data/evals/retrieval_cases_review.md`，源条款和用例哈希、分类、标注状态记录在 `data/evals/retrieval_annotation_manifest.json`。
问题只指定需直接命中的核心条款；已批准的范围与父条款上下文由 evidence-api 按 context_clause_uids 补全，不重复塞入每题的检索目标。
多条款题需同时检查 all_targets_recalled_rate；无答案题可能仍召回相似候选，no_answer_candidate_rate 不等同最终报告的误引率。

准备标注与运行评测分开。先完成条款导入和 sync-dify，再使用本地 `.venv` 执行：

```powershell
.\.venv\Scripts\uv.exe run python -m app.cli evaluate-retrieval --cases evals/retrieval_cases.jsonl
```
