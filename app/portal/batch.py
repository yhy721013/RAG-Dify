"""本地门户批处理客户端；auto 显式使用机器检查模式，不伪造人工批准。"""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.errors import DomainError
from ingestion.mineru_adapter import file_sha256
from ingestion.sync_dify import atomic_json


class BatchClient:
    def __init__(self, origin="http://127.0.0.1:8001", client=None):
        parsed = urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
                or parsed.port != 8001 or parsed.path not in {"", "/"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("批处理入口只接受本机 http://127.0.0.1:8001 或 localhost:8001")
        self.origin = origin.rstrip("/")
        self.client = client or httpx.Client(base_url=self.origin, timeout=120, trust_env=False,
                                             follow_redirects=False)

    def connect(self):
        state = self.request("GET", "/api/status")
        self.client.headers.update({"Origin": self.origin, "X-CSRF-Token": state["csrf_token"]})

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        try:
            value = response.json()
        except ValueError as error:
            raise DomainError("invalid_response", f"门户返回非 JSON，HTTP {response.status_code}") from error
        if response.is_error:
            detail = value.get("error", {})
            raise DomainError(detail.get("code", "batch_http_error"),
                              detail.get("message", f"HTTP {response.status_code}"),
                              status=response.status_code, details=detail.get("details", {}))
        return value

    def wait(self, job_id, timeout, interval=2):
        deadline = time.monotonic() + timeout
        while True:
            job = self.request("GET", f"/api/jobs/{job_id}")
            if job["status"] not in {"queued", "running"}:
                return job
            if time.monotonic() >= deadline:
                raise DomainError("batch_wait_timeout", f"等待超时，任务 {job_id} 仍保留；用 status 查询，未取消或重发")
            time.sleep(interval)


def load_manifest(path, origin):
    if not path.exists():
        return {"version": 1, "origin": origin, "files": []}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("version") != 1 or value.get("origin") != origin or not isinstance(value.get("files"), list):
        raise ValueError("批次清单版本或门户地址不匹配")
    return value


def ingest(api, directory, manifest_path, timeout, recursive=False):
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("input-dir 必须为目录")
    paths = sorted(p for p in (directory.rglob("*") if recursive else directory.iterdir())
                   if p.is_file() and p.suffix.lower() == ".pdf")
    if not paths:
        raise ValueError("目录中没有 PDF")
    manifest = load_manifest(manifest_path, api.origin)
    for path in paths:
        checksum = file_sha256(path)
        entry = next((row for row in manifest["files"] if row["sha256"] == checksum), None)
        if entry is None:
            entry = {"path": str(path), "sha256": checksum, "status": "upload_pending"}
            manifest["files"].append(entry)
        try:
            if not entry.get("document_id"):
                atomic_json(manifest_path, manifest)
                with path.open("rb") as stream:
                    uploaded = api.request("POST", "/api/documents",
                                           files={"file": (path.name, stream, "application/pdf")})
                entry.update(document_id=uploaded["document_id"], reused=uploaded["reused"],
                             job_id=(uploaded.get("parse_job") or {}).get("id"), status="uploaded")
                atomic_json(manifest_path, manifest)
            doc = api.request("GET", f'/api/documents/{entry["document_id"]}')
            if doc["sha256"] != checksum:
                raise ValueError("门户文档哈希与批次清单不一致")
            if entry.get("job_id"):
                job = api.wait(entry["job_id"], timeout)
                entry["status"] = job["status"]
                entry["error"] = job.get("error", {})
                if job["status"] != "succeeded":
                    atomic_json(manifest_path, manifest)
                    continue
                doc = api.request("GET", f'/api/documents/{entry["document_id"]}')
            payload = doc["payload"]
            entry.update(status="parsed" if payload.get("candidates") else "not_parsed",
                         candidate_count=len(payload.get("candidates", [])),
                         full_document_covered=payload.get("normalized", {}).get("full_document_covered"),
                         error={})
            atomic_json(manifest_path.parent / (entry["document_id"] + ".review.json"), doc)
        except (DomainError, httpx.HTTPError, ValueError, OSError) as error:
            entry.update(status="needs_attention", error={"type": type(error).__name__,
                         "message": str(error) if not isinstance(error, httpx.HTTPError) else "网络错误；查询原任务，勿盲目重发"})
        atomic_json(manifest_path, manifest)
    return manifest


def preview(api, manifest_path, output):
    manifest = load_manifest(manifest_path, api.origin)
    ids = sorted({row["document_id"] for row in manifest["files"] if row.get("document_id")})
    if not ids:
        raise ValueError("批次中没有已上传文档")
    result = api.request("POST", "/api/releases/preview", json={"document_ids": ids})
    atomic_json(output, {"origin": api.origin, "document_ids": ids, "preview": result})
    return result


def publish(api, preview_path, cases_path, actor, confirm_replacements, manifest_path, timeout):
    saved = json.loads(preview_path.read_text(encoding="utf-8-sig"))
    if saved.get("origin") != api.origin:
        raise ValueError("预览与当前门户不一致")
    cases = json.loads(cases_path.read_text(encoding="utf-8-sig"))
    if not actor.strip() or not isinstance(cases, list) or not cases:
        raise ValueError("须提供实际复核人及人工核对的问题数组")
    manifest = load_manifest(manifest_path, api.origin)
    if manifest.get("publish_intent"):
        raise ValueError("本清单已有发布意图；使用 status 对账，不能盲目重新发布")
    payload = {"document_ids": saved["document_ids"], "preview_hash": saved["preview"]["preview_hash"],
               "actor": actor.strip(), "cases": cases, "confirm_replacements": confirm_replacements}
    draft = saved["preview"].get("case_draft", {})
    if any(row.get("case_id", "").startswith("draft_") for row in cases):
        payload.update(case_draft_id=draft.get("id", ""),
                       confirmed_case_ids=[row["case_id"] for row in cases])
    manifest["publish_intent"] = {"preview_hash": payload["preview_hash"], "status": "submitting"}
    atomic_json(manifest_path, manifest)
    job = api.request("POST", "/api/releases", json=payload)
    manifest["publish_intent"].update(job_id=job["id"], status=job["status"])
    atomic_json(manifest_path, manifest)
    result = api.wait(job["id"], timeout)
    manifest["publish_intent"].update(status=result["status"], result=result.get("result"), error=result.get("error"))
    atomic_json(manifest_path, manifest)
    return result


def automated(api, directory, manifest_path, timeout, recursive=False, metadata_path=None,
              confirm_replacements=False):
    manifest = load_manifest(manifest_path, api.origin)
    intent = manifest.get("publish_intent")
    if intent:
        if not intent.get("job_id"):
            raise ValueError("已有结果未知的发布意图，请先用 status 和任务页对账，不重发")
        # 同一批次重启只等待原任务；新增文件使用另一个批次清单。
        result = api.wait(intent["job_id"], timeout)
        intent.update(status=result["status"], result=result.get("result"), error=result.get("error"))
        atomic_json(manifest_path, manifest)
        return result
    manifest = ingest(api, directory, manifest_path, timeout, recursive)
    if any(r["status"] != "parsed" for r in manifest["files"]):
        return {"status": "needs_attention", "files": manifest["files"]}
    supplied = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path else {}
    if not isinstance(supplied, dict):
        raise ValueError("metadata 须为按文档 ID 或文件 SHA-256 索引的对象")
    entries = manifest["files"]
    known = {r[k] for r in entries for k in ("document_id", "sha256")}
    if set(supplied) - known:
        raise ValueError("metadata 包含不属于本批次的文档 ID 或 SHA-256")
    metadata = {r["document_id"]: supplied.get(r["document_id"], supplied.get(r["sha256"], {})) for r in entries}
    payload = {"document_ids": sorted({r["document_id"] for r in entries}), "mode": "automated", "metadata": metadata}
    value = api.request("POST", "/api/releases/preview", json=payload)
    atomic_json(manifest_path.parent / "automated-preview.json", value)
    if value.get("blockers"):
        return {"status": "blocked", "blockers": value["blockers"], "excluded": value.get("excluded", [])}
    if value["unchanged"]:
        return {"status": "unchanged", "snapshot_id": value["parent"]}
    if value["replacements"] and not confirm_replacements:
        raise ValueError("涉及同标准条款集合替换；查看 automated-preview.json 后用 --confirm-replacements 明确选择")
    payload.update(preview_hash=value["preview_hash"], confirm_replacements=confirm_replacements)
    manifest["publish_intent"] = {"mode": "automated", "preview_hash": value["preview_hash"], "status": "submitting"}
    atomic_json(manifest_path, manifest)
    job = api.request("POST", "/api/releases", json=payload)
    manifest["publish_intent"].update(job_id=job["id"], status=job["status"])
    atomic_json(manifest_path, manifest)
    result = api.wait(job["id"], timeout)
    manifest["publish_intent"].update(status=result["status"], result=result.get("result"), error=result.get("error"))
    atomic_json(manifest_path, manifest)
    return {**result, "excluded": value.get("excluded", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8001")
    sub = parser.add_subparsers(dest="command", required=True)
    upload = sub.add_parser("ingest", help="批量上传并等待解析，导出复核数据")
    upload.add_argument("--input-dir", type=Path, required=True)
    upload.add_argument("--recursive", action="store_true")
    pre = sub.add_parser("preview", help="导出已批准集合的发布预览")
    pre.add_argument("--output", type=Path, required=True)
    pub = sub.add_parser("publish", help="发布人工核对后的预览和问题；不批准条款")
    pub.add_argument("--preview", type=Path, required=True)
    pub.add_argument("--cases", type=Path, required=True)
    pub.add_argument("--actor", required=True)
    pub.add_argument("--confirm-replacements", action="store_true")
    status = sub.add_parser("status", help="只读查询批次原任务")
    auto = sub.add_parser("auto", help="自动上传、解析、机器检查、索引回查和发布；未经人工复核")
    auto.add_argument("--input-dir", type=Path, required=True)
    auto.add_argument("--recursive", action="store_true")
    auto.add_argument("--metadata", type=Path, help="按文件 SHA-256 或文档 ID 补充身份与范围的 JSON")
    auto.add_argument("--confirm-replacements", action="store_true")
    for cmd in (upload, pre, pub, status, auto):
        cmd.add_argument("--manifest", type=Path, required=True)
    for cmd in (upload, pub, auto):
        cmd.add_argument("--timeout", type=int, default=14400)
    args = parser.parse_args()
    api = BatchClient(args.origin)
    try:
        api.connect()
        if hasattr(args, "timeout") and args.timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if args.command == "ingest":
            result = ingest(api, args.input_dir, args.manifest, args.timeout, args.recursive)
        elif args.command == "preview":
            result = preview(api, args.manifest, args.output)
        elif args.command == "publish":
            result = publish(api, args.preview, args.cases, args.actor, args.confirm_replacements,
                             args.manifest, args.timeout)
        elif args.command == "auto":
            result = automated(api, args.input_dir, args.manifest, args.timeout, args.recursive,
                               args.metadata, args.confirm_replacements)
        else:
            manifest = load_manifest(args.manifest, api.origin)
            ids = {row["job_id"] for row in manifest["files"] if row.get("job_id")}
            if manifest.get("publish_intent", {}).get("job_id"):
                ids.add(manifest["publish_intent"]["job_id"])
            result = {"jobs": [api.request("GET", f"/api/jobs/{uid}") for uid in sorted(ids)],
                      "publish_intent": manifest.get("publish_intent")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "ingest" and any(row["status"] != "parsed" for row in result["files"]):
            raise SystemExit(2)
        if args.command == "publish" and result["status"] != "succeeded":
            raise SystemExit(2)
        if args.command == "auto" and result.get("status") not in {"succeeded", "unchanged"}:
            raise SystemExit(2)
    except (DomainError, ValueError, OSError, httpx.HTTPError) as error:
        print(json.dumps({"error": error.detail() if isinstance(error, DomainError) else str(error) if not isinstance(error, httpx.HTTPError) else
                          "网络请求失败；已保存批次清单，请查询原任务"}, ensure_ascii=False))
        raise SystemExit(2) from error
    finally:
        api.close()


if __name__ == "__main__":
    main()
