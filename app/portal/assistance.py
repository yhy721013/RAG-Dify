"""确定性整理建议；不修改原文、不替人批准，也不查询标准的现行状态。"""
import re
from collections import Counter
from difflib import unified_diff

from app.errors import DomainError
from app.repository import digest
from ingestion.mineru_adapter import file_sha256, local_path

VERSION = "rules-v1"
STANDARD = re.compile(r"GB\s*(?:/\s*([TZ]))?\s*(\d{3,6}(?:\.\d+)?)\s*[-—–－]\s*((?:19|20)\d{2})", re.I)
NUMBER = re.compile(r"^(?:[1-9]\d*(?:\.\d+)*|[A-Z](?:\.\d+)*)$")
UNITS = r"mm|cm|km|m|kg|mg|g|kN|N|MPa|kPa|Pa|kW|W|V|A|Hz|s|℃|°C|%|°"
NUMBERS = re.compile(rf"(?<![\w.])\d+(?:[.,．]\s*\d+)?\s*(?:{UNITS})(?![A-Za-z])", re.I)


def blocks(payload):
    return {b["block_id"]: (page, b) for page in payload.get("normalized", {}).get("pages", []) for b in page["blocks"]}


def metadata_draft(payload):
    source = [(p, b) for p in payload.get("normalized", {}).get("pages", [])[:6] for b in p["blocks"]]
    values, provenance = {}, {}
    for page, block in source:
        if re.match(r"\s*(?:代替|替代)", block["text"]):
            continue
        match = STANDARD.search(block["text"])
        if match:
            code = "GB" + ("/" + match[1].upper() if match[1] else "") + " " + match[2] + "-" + match[3]
            values.update(standard_code=code, edition=match[3])
            provenance["standard_code"] = {"page": page["pdf_page_index"] + 1, "block_id": block["block_id"], "rule": "封面/前部标准编号"}
            provenance["edition"] = provenance["standard_code"]
            break
    titles = [(p, b) for p, b in source if p["pdf_page_index"] == 0 and b["block_type"] == "doc_title"
              and re.search(r"[\u4e00-\u9fff]{2}", b["text"].replace(" ", ""))
              and not re.search(r"中华人民共和国|国家标准|代替|发布|实施|^\s*GB", b["text"].replace(" ", ""), re.I)]
    if titles:
        values["standard_name"] = " ".join(re.sub(r"\s+", " ", b["text"]).strip() for _, b in titles)
        provenance["standard_name"] = {"page": 1, "block_ids": [b["block_id"] for _, b in titles], "rule": "封面中文标题块"}
    scope = next((r["record"] for r in payload.get("candidates", []) if r["record"]["clause_no"] == "1"
                  and re.match(r"\s*1\s*范\s*围", r["record"]["text_verbatim"])), None)
    if scope:
        values["scope"] = re.sub(r"^\s*1\s*范\s*围\s*", "", scope["text_verbatim"]).strip()
        provenance["scope"] = {"pages": sorted({s["pdf_page_index"] + 1 for s in scope["source_spans"]}), "rule": "第1章范围原文"}
    return {"values": values, "provenance": provenance, "requires_confirmation": True,
            "note": "规则预填须对照PDF；标准状态、核验日期和来源须人工核验，不从发布日期推断现行状态。"}


def standard_key(payload):
    meta = {**metadata_draft(payload)["values"], **payload.get("metadata", {})}
    return re.sub(r"\s+", "", meta.get("standard_code", "")).replace("—", "-"), meta.get("edition", "")


def choose_baseline(doc, documents, historical=None, baseline_id=""):
    key = standard_key(doc["payload"])
    choices = [d for d in documents if d["id"] != doc["id"] and key[0] and key == standard_key(d["payload"])
               and any(i["record"]["content_review_status"] == "approved" for i in d["payload"].get("candidates", []))]
    if baseline_id:
        selected = next((d for d in choices if d["id"] == baseline_id), None)
        if not selected:
            raise DomainError("baseline_mismatch", "对照基准须为同标准/版本且有批准记录的文件", status=409)
    else:
        selected = max(choices, key=lambda d: (d["created_at"], d["id"]), default=None) or historical
    return selected, [{"id": d["id"], "filename": d["filename"], "revision": d["revision"]} for d in choices]


def comparison(payload, previous):
    if not previous:
        return {}, []
    old_items = previous.get("candidates", [])
    old_counts = Counter(tuple(i["record"]["clause_path"]) for i in old_items)
    old = {tuple(i["record"]["clause_path"]): i["record"] for i in old_items}
    current = {tuple(i["record"]["clause_path"]): i["record"] for i in payload.get("candidates", [])}
    old_keys = {r["clause_uid"]: key for key, r in old.items() if r.get("clause_uid")}
    new_keys = {r["clause_uid"]: key for key, r in current.items() if r.get("clause_uid")}
    changes, directly_changed = {}, set(old) - set(current)
    metadata_changed = bool(payload.get("metadata")) and payload["metadata"] != previous.get("metadata", {})
    for item in payload.get("candidates", []):
        record, key = item["record"], tuple(item["record"]["clause_path"])
        before = old.get(key)
        fields = []
        if before:
            if before["text_verbatim"] != record["text_verbatim"]: fields.append("text")
            if sorted(before.get("asset_sha256", {}).values()) != sorted(record.get("asset_sha256", {}).values()): fields.append("assets")
            if item.get("context_reviewed") and {new_keys.get(u, u) for u in record["context_clause_uids"]} != {old_keys.get(u, u) for u in before["context_clause_uids"]}: fields.append("context")
            if metadata_changed: fields.append("metadata")
        state = "added" if not before else "ambiguous" if old_counts[key] > 1 else "modified" if fields else "unchanged"
        if state != "unchanged": directly_changed.add(key)
        changes[item["id"]] = {"status": state, "fields": fields, "previous_text": before["text_verbatim"] if before else "",
            "previous_approved": bool(before and before["content_review_status"] == "approved"),
            "text_diff": list(unified_diff(before["text_verbatim"].splitlines(), record["text_verbatim"].splitlines(), lineterm=""))[:80] if before and "text" in fields else []}
    affected = set(directly_changed)
    while True:
        dependent = {key for key, r in old.items() if any(old_keys.get(u) in affected for u in r["context_clause_uids"])}
        dependent |= {key for key, r in current.items() if any(new_keys.get(u) in affected for u in r["context_clause_uids"])}
        if dependent <= affected: break
        affected |= dependent
    for item in payload.get("candidates", []):
        row = changes[item["id"]]
        if row["status"] == "unchanged" and tuple(item["record"]["clause_path"]) in affected:
            row["status"] = "dependency_affected"
    removed = [{"clause_no": old[key]["clause_no"], "text": old[key]["text_verbatim"]} for key in sorted(set(old) - set(current))]
    return changes, removed


def analyze(doc, data_root, documents=(), historical=None, baseline_id=""):
    payload = doc["payload"]
    normalized = payload.get("normalized", {})
    items = payload.get("candidates", [])
    source = blocks(payload)
    baseline, choices = choose_baseline(doc, documents, historical, baseline_id)
    previous = baseline["payload"] if baseline else None
    changes, removed = comparison(payload, previous)
    draft = metadata_draft(payload)
    checks = []
    if normalized.get("source_file_sha256") and doc.get("source_path"):
        try:
            archived = local_path(data_root, doc["source_path"])
            if not archived.is_file() or file_sha256(archived) != normalized["source_file_sha256"]:
                checks.append({"code": "source_archive_changed", "severity": "block", "message": "归档PDF缺失或内容发生变化，不能沿用复核"})
        except DomainError:
            checks.append({"code": "source_archive_changed", "severity": "block", "message": "原始PDF归档路径无效"})
    missing = normalized.get("missing_pages", [])
    if normalized and not normalized.get("full_document_covered"):
        checks.append({"code": "missing_pages", "severity": "block", "message": "整份PDF页覆盖未确认完整", "pages": [p + 1 for p in missing]})
    empty = [p["pdf_page_index"] + 1 for p in normalized.get("coverage", []) if p["status"] == "empty_page_requires_review"]
    if empty:
        checks.append({"code": "empty_pages", "severity": "warning", "message": "解析为空的页面须对照原PDF确认确为空白", "pages": empty})
    order_pages = set()
    for page in normalized.get("pages", []):
        indices = [int(b["block_id"].rsplit("_b", 1)[1]) for b in page["blocks"] if re.fullmatch(r"p\d+_b\d+", b["block_id"])]
        if indices != sorted(indices): order_pages.add(page["pdf_page_index"] + 1)
    counts = Counter(tuple(i["record"]["clause_path"]) for i in items)
    by_no = {}
    for item in items: by_no.setdefault(item["record"]["clause_no"], []).append(item)
    figures = {m.group(0).replace(" ", "") for m in re.finditer(r"(?:图|表)\s*[A-Z]?\.?\d+(?:\.\d+)*", "\n".join(b["text"] for _, b in source.values() if b["block_type"] in {"table", "image", "chart", "caption", "paragraph_title"}))}
    rows, sibling_last = [], {}
    for item in items:
        r = item["record"]
        number, path, text = r["clause_no"], tuple(r["clause_path"]), r["text_verbatim"]
        issues, suggestions = [], []
        def issue(code, message, severity="warning", **detail):
            if not any(v["code"] == code for v in issues): issues.append({"code": code, "message": message, "severity": severity, **detail})
        def suggest(target, reason):
            targets = by_no.get(target, [])
            if len(targets) == 1 and targets[0]["id"] != item["id"]:
                other = targets[0]
                if target.startswith(number + "."):
                    return  # 子条款不能反向作为父条款的必要依赖，避免建议自身形成层级环。
                if not any(x["candidate_id"] == other["id"] for x in suggestions):
                    suggestions.append({"candidate_id": other["id"], "clause_uid": other["record"].get("clause_uid", ""), "clause_no": target, "reason": reason})
        if not NUMBER.fullmatch(number) or not path or path[-1] != number:
            issue("number_unknown", "编号或层级不明确，须明确边界", "block")
        elif counts[path] > 1:
            issue("number_duplicate", "同一路径出现重复编号", "block")
        else:
            parts = number.split(".")
            parent = ".".join(parts[:-1])
            if parent and parent not in by_no:
                issue("parent_missing", "未找到父条款，核对编号和解析层级", parent=parent)
            if parts[-1].isdigit():
                last, current = sibling_last.get(parent), int(parts[-1])
                if last is not None and current != last + 1:
                    issue("number_sequence", "同级编号不连续或顺序异常", previous=last, current=current)
                sibling_last[parent] = current
            if parent: suggest(parent, "编号识别的直接父条款，需核对是否提供必要前提")
            if number != "1" and not number.startswith("unassigned"): suggest("1", "标准适用范围，需确认关联")
        pages = sorted({s["pdf_page_index"] + 1 for s in r["source_spans"]})
        if order_pages.intersection(pages): issue("reading_order", "来源块顺序异常，核对栏位与阅读顺序")
        if len(pages) > 1:
            issue("cross_page_join", "条款跨页，核对末句与下一页首句是否连续", pages=pages)
        selected = [source.get(bid) for span in r["source_spans"] for bid in span["block_ids"]]
        if not selected or any(v is None for v in selected): issue("source_missing", "来源块缺失", "block")
        for value in selected:
            if value is None: continue
            _, block = value
            for flag in block["review_issues"]:
                if flag == "visual_asset_unconfirmed" or flag.startswith(("missing_asset:", "unsafe_asset:", "unsupported_block_type:")):
                    issue("asset_missing", "图表资产或解析结构未完整确认", "block", detail=flag)
            if block["block_type"] in {"image", "table", "chart", "equation"}:
                issue("visual_review", "含图表或公式，逐项核对内容与阅读顺序")
        for ref in r["asset_refs"]:
            try:
                asset = local_path(data_root, ref)
                if not asset.is_file() or file_sha256(asset) != r.get("asset_sha256", {}).get(ref):
                    issue("asset_missing", "图表缺失或哈希变化", "block")
            except DomainError: issue("asset_missing", "图表路径无效", "block")
        for ref in re.findall(r"(?:图|表)\s*[A-Z]?\.?\d+(?:\.\d+)*", text):
            if ref.replace(" ", "") not in figures:
                issue("figure_reference", "引用图表未在已识别图表/标题中定位，需核对是否为外部引用", reference=ref)
        suspected = re.findall(rf"\d[OoＯIlｌ]\s*(?:{UNITS})|\d[.．,]\s+\d|\d\s*[~～至]\s*(?:{UNITS})(?!\w)|�", text, re.I)
        if suspected: issue("numeric_ocr", "数字、单位或字符存在疑点，不自动改写", samples=list(dict.fromkeys(suspected))[:15])
        if len(re.findall(r"[（(]", text)) != len(re.findall(r"[）)]", text)):
            issue("sentence_fragment", "括号不配对，核对是否缺句、跨页或OCR遗漏")
        for target in re.findall(r"(?:见|参见|按照|根据)\s*(\d+(?:\.\d+)+|[A-Z](?:\.\d+)+)", text):
            if target in by_no: suggest(target, "正文出现条款引用，需确认是否为本标准及必要上下文")
            else: issue("context_reference", "引用条款未在本文件定位，核对外部引用及必要上下文", reference=target)
        if previous:
            old = next((i["record"] for i in previous.get("candidates", []) if tuple(i["record"]["clause_path"]) == path), None)
            old_uids = {i["record"].get("clause_uid"): i["record"]["clause_no"] for i in previous.get("candidates", [])}
            if old and old["content_review_status"] == "approved":
                for uid in old["context_clause_uids"]:
                    if uid in old_uids: suggest(old_uids[uid], "原批准记录的上下文，须核对新来源和前提未变")
        hard = any(v["severity"] == "block" for v in [*checks, *issues])
        approved = r["content_review_status"] == "approved" and not hard
        required = [v for v in suggestions if v["clause_uid"] and v["clause_uid"] not in r["context_clause_uids"]]
        normal = not issues and not any(c["severity"] == "block" for c in checks)
        rows.append({"candidate_id": item["id"], "clause_no": number, "clause_path": r["clause_path"], "pages": pages,
            "issues": issues, "suggested_context": suggestions, "context_needs_confirmation": bool(required) and not item.get("context_reviewed", False),
            "number_unit_samples": list(dict.fromkeys(NUMBERS.findall(text)))[:30],
            "group": "reviewed" if approved else "normal" if normal else "exception", "hard_blocked": hard,
            "diff": changes.get(item["id"], {"status": "new", "fields": [], "previous_text": "", "previous_approved": False})})
    graph = {r["candidate_id"]: {s["candidate_id"] for s in r["suggested_context"]} for r in rows}
    for row in rows:
        frontier, visited = list(graph[row["candidate_id"]]), set()
        while frontier:
            node = frontier.pop()
            if node == row["candidate_id"]:
                row["issues"].append({"code": "context_cycle_suggestion", "severity": "warning", "message": "上下文建议之间可能成环，请逐项选择必要前提，不要整组采纳"})
                if row["group"] == "normal": row["group"] = "exception"
                break
            if node not in visited:
                visited.add(node)
                frontier.extend(graph.get(node, set()))
    return {"version": VERSION, "metadata_draft": draft, "document_checks": checks, "rows": rows,
        "baseline": {k: baseline[k] for k in ("id", "filename", "revision", "sha256")} if baseline else None,
        "baseline_choices": choices, "removed": removed, "counts": dict(Counter(r["group"] for r in rows)),
        "review_hash": digest({"version": VERSION, "revision": doc["revision"], "payload": digest(payload), "rows": rows, "checks": checks,
                               "baseline": [baseline["id"], baseline["revision"], digest(previous)] if baseline else None}),
        "limitation": "无规则疑点不等于文字正确；全部建议和数字单位仍须对照PDF。文件内容变化时不自动继承新来源的批准。"}


def retrieval_drafts(preview):
    drafts = []
    for record in preview["records"]:
        lines = record["text_verbatim"].splitlines()
        if len(lines) == 1 and not re.search(r"[。；;]", lines[0]):
            continue  # 只有章节标题时不假设其包含可以标注的答案。
        title = re.sub(r"^\s*" + re.escape(record["clause_no"]) + r"\s*", "", lines[0]).strip()
        topic = title if 3 <= len(title) <= 45 and title not in {"一般要求", "概述", "范围"} else "".join(lines[1:])[:55] or title
        if not topic: topic = record["standard_name"][:45]
        drafts.append({"case_id": "draft_" + digest(record["clause_uid"])[:16],
            "query": f"针对“{topic[:70]}”，标准提出了哪些要求和适用前提？", "answerable": True,
            "expected_clause_uids": [record["clause_uid"]]})
        if len(drafts) == 100: break
    return {"id": digest([preview["preview_hash"], drafts]), "cases": drafts, "provenance": VERSION,
            "requires_confirmation": True, "truncated": len(preview["records"]) > 100}
