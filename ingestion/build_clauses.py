import json
import re
from collections import Counter
from pathlib import Path

from app.errors import DomainError
from app.reporting import safe_text
from app.repository import json_text
from ingestion.mineru_adapter import adapt, file_sha256, local_path, unpack

CLAUSE = re.compile(r"^\s*((?:[1-9]\d*)(?:\.\d+)*|[A-Z](?:\.\d+)+)(?:\s+|(?=[\u4e00-\u9fff]))\S")
APPENDIX = re.compile(r"^\s*附\s*录\s*([A-Z])(?:\s|$)")
TOC = re.compile(r"(?:\.{4,}|…{2,}|·{4,})")


def candidates(document: dict, data_root: Path) -> list[dict]:
    output, current, appendix_section = [], None, None
    for page in document["pages"]:
        for block in page["blocks"]:
            kind, text = block["block_type"], block["text"]
            if kind in {"index", "header", "footer", "page_number", "aside_text"} or TOC.search(text):
                continue
            appendix = APPENDIX.match(text)
            # 图表单元格中的数字不作为新条款；独立标题编号可与下一块正文衔接。
            match = CLAUSE.match(text) if kind in {"text", "paragraph_title", "doc_title"} else None
            bare = re.fullmatch(r"\s*((?:[1-9]\d*)(?:\.\d+)*|[A-Z](?:\.\d+)+)\s*", text) if kind == "paragraph_title" else None
            if appendix:
                appendix_section = appendix.group(1)
            number = appendix.group(1) if appendix else match.group(1) if match else bare.group(1) if bare else None
            if number or current is None:
                if current:
                    output.append(current)
                number = number or f"unassigned_p{page['pdf_page_index']}"
                parts = number.split(".")
                path = [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
                if appendix_section and number[0].isdigit():
                    path.insert(0, appendix_section)
                current = {key: document[key] for key in ("source_file_sha256", "source_archive_path", "source_page_count",
                                                         "parser_version", "full_document_covered")}
                current.update(standard_uid="", standard_code="", standard_name="", edition="", scope="",
                    clause_uid="", clause_no=number, clause_path=path, text_verbatim="", source_spans=[], asset_refs=[],
                    context_clause_uids=[], content_review_status="pending", evidence_complete=False, is_test_fixture=False,
                    boundary_status="unknown" if number.startswith("unassigned") else "pending",
                    review_issues=["text_review_required", "standard_metadata_required", "boundary_review_required", "context_review_required"])
            current["text_verbatim"] += ("\n" if current["text_verbatim"] else "") + text
            current["source_spans"].append({"pdf_page_index": page["pdf_page_index"],
                "printed_page_label": page["printed_page_label"], "block_ids": [block["block_id"]], "bbox": block["bbox"]})
            current["asset_refs"].extend(block["asset_refs"])
            current["review_issues"].extend(block["review_issues"])
            if kind in {"table", "image", "chart", "equation"}:
                current["review_issues"].append("figure_or_table_review_required")
    if current:
        output.append(current)
    counts = Counter(tuple(item["clause_path"]) for item in output)
    for item in output:
        if len({span["pdf_page_index"] for span in item["source_spans"]}) > 1:
            item["review_issues"].append("cross_page_review_required")
        if counts[tuple(item["clause_path"])] > 1:
            item["boundary_status"] = "unknown"
            item["review_issues"].append("duplicate_clause_number")
        if not document["full_document_covered"]:
            item["review_issues"].append("incomplete_page_coverage")
        item["asset_refs"] = sorted(set(item["asset_refs"]))
        item["review_issues"] = sorted(set(item["review_issues"]))
        item["asset_sha256"] = {ref: file_sha256(local_path(data_root, ref)) for ref in item["asset_refs"]
                                if local_path(data_root, ref).is_file()}
        if not item["text_verbatim"]:
            item["text_verbatim"] = "【无可提取文本：需对照原始图表人工转录】"
    return output


def build_directory(input_dir: Path, output_file: Path, data_root: Path):
    if not input_dir.is_dir():
        raise DomainError("parse_error", "MinerU 输入目录不存在", "input")
    for package in sorted(input_dir.glob("*.zip")):
        unpack(package, input_dir / package.stem)
    exports = sorted(input_dir.rglob("middle_json.json"))
    if not exports:
        raise DomainError("parse_error", "没有找到 MinerU 完整导出包", "input")
    all_candidates, results = [], []
    for middle in exports:
        export = middle.parent
        sidecar = export / "source.json"
        info = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        source = local_path(data_root, info.get("source_archive_path", f"raw_pdf/{export.name}.pdf"))
        try:
            document = adapt(export, source, data_root)
            items = candidates(document, data_root)
            all_candidates.extend(items)
            (export / "normalized.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({"export": str(export), "source_archive_path": document["source_archive_path"],
                            "status": "pending_review", "candidate_count": len(items),
                            "full_document_covered": document["full_document_covered"], "coverage": document["coverage"]})
        except (DomainError, OSError, ValueError, KeyError) as error:
            results.append({"export": str(export), "status": "parse_error", "error": str(error)})
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("".join(json_text(item) + "\n" for item in all_candidates), encoding="utf-8")
    markdown = ["# 待人工复核条款\n", "全部内容均未批准；页码标签也需对照原 PDF 核验。\n"]
    for item in all_candidates:
        pages = sorted({span["pdf_page_index"] + 1 for span in item["source_spans"]})
        markdown.extend([f"## {safe_text(item['source_archive_path'])} — 候选 {safe_text(item['clause_no'])}\n",
                         f"PDF 页：{pages}；问题：{safe_text(', '.join(item['review_issues']))}\n",
                         safe_text(item["text_verbatim"]) + "\n"])
    output_file.with_suffix(".md").write_text("\n".join(markdown), encoding="utf-8")
    output_file.with_suffix(".manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(item["status"] == "parse_error" for item in results):
        raise DomainError("parse_error", "部分文件解析失败，详情见 manifest；成功文件仍输出为待复核")
    return {"files": len(results), "candidates": len(all_candidates), "review_status": "pending"}
