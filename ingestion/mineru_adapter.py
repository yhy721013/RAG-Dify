"""MinerU 4.0.2 / docvortex.middle 2.0 完整导出包适配。"""
import hashlib
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from pypdf import PdfReader

from app.errors import DomainError


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def local_path(root: Path, reference: str) -> Path:
    path = (root / reference).resolve()
    if not reference or Path(reference).is_absolute() or ":" in reference or not path.is_relative_to(root.resolve()):
        raise DomainError("parse_error", "资产路径必须位于归档目录内", "asset_refs")
    return path


def unpack(package: Path, destination: Path):
    """保留 ZIP；只解包本地相对路径，不跟随链接或覆盖已有文件。"""
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        if sum(info.file_size for info in archive.infolist()) > 1024 ** 3:
            raise DomainError("parse_error", "解析包解包体积超过 1 GiB")
        for info in archive.infolist():
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise DomainError("parse_error", "解析包禁止包含符号链接")
            target = local_path(destination, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                content = archive.read(info)
                if target.exists() and target.read_bytes() != content:
                    raise DomainError("parse_error", "解包位置已有不同内容，请使用新目录")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)


def content_text(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        inline = all(isinstance(item, dict) and item.get("type") in {"text", "equation_inline", "link"}
                     and isinstance(item.get("content"), str) for item in node)
        return ("" if inline else "\n").join(content_text(item) for item in node)
    if isinstance(node, dict):
        return content_text(node.get("content", ""))
    raise DomainError("parse_error", "未知 MinerU content 结构", "content")


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.references.extend(value for key, value in attrs if key == "src" and value)


def asset_references(node):
    refs = []
    if isinstance(node, dict):
        refs.extend(node[key] for key in ("image_path", "image_url") if node.get(key))
        refs.extend(asset_references(node.get("content", "")))
    elif isinstance(node, list):
        for item in node:
            refs.extend(asset_references(item))
    elif isinstance(node, str) and "<img" in node.lower():
        parser = AssetParser()
        parser.feed(node)
        refs.extend(parser.references)
    return sorted(set(refs))


def adapt(export_dir: Path, source_pdf: Path, data_root: Path) -> dict:
    for name in ("markdown.md", "middle_json.json", "structured_content.json"):
        if not (export_dir / name).is_file():
            raise DomainError("parse_error", "缺少完整导出文件：" + name)
    raw = json.loads((export_dir / "middle_json.json").read_text(encoding="utf-8"))
    if raw.get("schema") != "docvortex.middle" or raw.get("schema_version") != "2.0":
        raise DomainError("parse_error", "需要 docvortex.middle 2.0，不接受旧版或项目内部示例结构")
    producer = raw.get("metadata", {}).get("producer", {})
    if producer != {"name": "mineru", "version": "4.0.2"}:
        raise DomainError("parse_error", "仅验证了 MinerU 4.0.2；其他版本需单独建立契约")
    page_count = len(PdfReader(source_pdf).pages)
    raw_pages = raw.get("pages")
    if not isinstance(raw_pages, list):
        raise DomainError("parse_error", "缺少 pages")
    seen, pages, coverage = set(), [], []
    known_types = {"text", "ref_text", "doc_title", "paragraph_title", "header", "footer", "page_number",
                   "aside_text", "page_footnote", "image", "table", "chart", "equation", "list", "index", "code", "algorithm"}
    for page in raw_pages:
        index = page.get("page_idx")
        if type(index) is not int or not 0 <= index < page_count or index in seen:
            raise DomainError("parse_error", "重复或越界 PDF 页索引", "page_idx")
        seen.add(index)
        blocks, block_indices = [], set()
        # 4.0.2 实际导出会省略空白页的默认空 blocks 字段。
        for block in page.get("blocks", []):
            block_index = block.get("index")
            if type(block_index) is not int or block_index < 0 or block_index in block_indices:
                raise DomainError("parse_error", "重复或无效块索引", "index")
            block_indices.add(block_index)
            refs, issues = [], []
            for ref in asset_references(block):
                try:
                    asset = local_path(export_dir, ref)
                    refs.append(asset.relative_to(data_root.resolve()).as_posix())
                    if not asset.is_file():
                        issues.append("missing_asset:" + ref)
                except (DomainError, ValueError):
                    issues.append("unsafe_asset:" + ref)
            if block["type"] not in known_types:
                issues.append("unsupported_block_type:" + block["type"])
            if block["type"] in {"image", "table", "chart", "equation"} and not refs:
                issues.append("visual_asset_unconfirmed")
            blocks.append({"block_id": f"p{index}_b{block_index}", "block_type": block["type"],
                           "text": content_text(block), "bbox": block.get("bbox"), "asset_refs": refs,
                           "review_issues": issues})
        labels = [block["text"] for block in blocks if block["block_type"] == "page_number"]
        pages.append({"pdf_page_index": index, "printed_page_label": labels[0] if len(labels) == 1 else None,
                      "blocks": blocks})
        coverage.append({"pdf_page_index": index, "status": "blocks_present" if blocks else "empty_page_requires_review",
                         "block_count": len(blocks)})
    missing = sorted(set(range(page_count)) - seen)
    coverage.extend({"pdf_page_index": index, "status": "missing_page", "block_count": 0} for index in missing)
    complete = not missing and raw.get("is_full_document") is True
    return {"source_file_sha256": file_sha256(source_pdf),
            "source_archive_path": source_pdf.resolve().relative_to(data_root.resolve()).as_posix(),
            "source_page_count": page_count, "parser_version": producer["version"],
            "parser_options": raw.get("extensions", {}).get("mineru", {}),
            "full_document_covered": complete, "missing_pages": missing,
            "pages": sorted(pages, key=lambda item: item["pdf_page_index"]),
            "coverage": sorted(coverage, key=lambda item: item["pdf_page_index"])}
