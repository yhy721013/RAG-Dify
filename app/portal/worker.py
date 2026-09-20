"""串行持久化任务进程；只通过官方 Service API 调用 Dify。"""
import argparse
import json
import os
import subprocess
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.dify_client import DifyClient
from app.errors import DomainError
from app.portal.repository import PortalRepository
from app.portal.settings import PortalSettings
from app.repository import Repository, json_text
from app.settings import ROOT
from app.safe_diagnostics import public_error
from evals.evaluate_retrieval import evaluate
from ingestion.build_clauses import candidates
from ingestion.import_reviewed import import_reviewed
from ingestion.mineru_adapter import adapt, local_path, unpack
from ingestion.sync_dify import activate_snapshot, atomic_json, sync_snapshot


@contextmanager
def worker_lock(path):
    """操作系统锁随进程退出释放，不把旧 PID 文件当成有效锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise DomainError("worker_locked", "已有后台任务进程运行", status=409) from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run_parser(command, log_path, timeout, tick):
    # 子进程只收到固定参数和归档路径；绝不拼接 shell 命令。
    with log_path.open("ab") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                tick()
                if time.monotonic() >= deadline:
                    raise DomainError("parse_timeout", "MinerU 解析超时，原文件和日志已保留")
                time.sleep(2)
            if process.returncode:
                raise DomainError("parse_error", "MinerU 未成功完成，展开任务诊断查看解析日志", details={"returncode": process.returncode})
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
                else:
                    process.terminate()
                process.wait(timeout=15)


def parse_document(job, store, config, parser=run_parser):
    doc = store.document(job["payload"]["document_id"])
    if doc["payload"].get("candidates"):
        return {"document_id": doc["id"], "candidate_count": len(doc["payload"]["candidates"]), "reused": True}
    if not config.mineru_executable.is_file():
        raise DomainError("configuration_error", "MinerU 独立虚拟环境尚未配置")
    directory = config.data_root / "mineru_output" / doc["id"] / uuid4().hex
    directory.mkdir(parents=True)
    result = {"document_id": doc["id"], "parse_directory": directory.relative_to(config.data_root).as_posix()}
    store.progress(job["id"], "parsing", result)
    parser([str(config.mineru_executable), "parse", str(local_path(config.data_root, doc["source_path"])),
            "-o", str(directory), "--pages", "all", "--format", "zip", "--tier", "standard", "--ocr-mode", "auto"],
           directory / "parser.log", config.parse_timeout_seconds, store.heartbeat)
    packages = list(directory.glob("*.zip"))
    if len(packages) != 1:
        raise DomainError("parse_error", "MinerU 未返回唯一完整 ZIP 导出包")
    unpack(packages[0], directory / "export")
    exports = list((directory / "export").rglob("middle_json.json"))
    if len(exports) != 1:
        raise DomainError("parse_error", "解析包中缺少唯一 middle_json.json")
    export = exports[0].parent
    atomic_json(export / "source.json", {"source_archive_path": doc["source_path"]})
    store.progress(job["id"], "candidates", result)
    normalized = adapt(export, local_path(config.data_root, doc["source_path"]), config.data_root)
    items = candidates(normalized, config.data_root)
    if not items:
        raise DomainError("parse_error", "解析没有产生任何候选条款")
    atomic_json(export / "normalized.json", normalized)
    payload = {"normalized": normalized, "metadata": {},
               "candidates": [{"id": "candidate_" + uuid4().hex, "record": row} for row in items]}
    atomic_json(directory / "candidates.original.json", payload)
    store.save_document(doc["id"], doc["revision"], payload, "pending_review", "mineru_parse", "system:mineru-4.0.2")
    return {**result, "candidate_count": len(items), "full_document_covered": normalized["full_document_covered"]}


def publish_release(job, store, config):
    payload = job["payload"]
    snapshot = payload["snapshot_id"]
    if any(row["snapshot_id"] == snapshot for row in store.releases()):
        return {"snapshot_id": snapshot, "published": True}
    if store.state("current_snapshot") != payload["parent"]:
        raise DomainError("release_conflict", "基础知识版本已变化，请重新预览后提交")
    settings = config.evidence_settings()
    repo = Repository(settings.db_path)
    repo.initialize()
    directory = config.data_root / "reviewed" / snapshot
    directory.mkdir(parents=True, exist_ok=True)
    approved, cases = directory / "approved.jsonl", directory / "cases.jsonl"
    approved.write_text("".join(json_text(row) + "\n" for row in payload["records"]), encoding="utf-8")
    cases.write_text("".join(json_text(row) + "\n" for row in payload["cases"]), encoding="utf-8")
    store.progress(job["id"], "importing", {"snapshot_id": snapshot})
    import_reviewed(approved, snapshot, repo, settings)
    with DifyClient(settings) as client:
        store.progress(job["id"], "indexing")
        sync_snapshot(snapshot, repo, settings, client)
        store.progress(job["id"], "evaluation")
        result = evaluate(cases, repo, settings, client, interval_seconds=7)
        if not result["passed"]:
            raise DomainError("retrieval_gate_failed", "检索自检未通过；保留候选版本，不能用于评估")
        store.progress(job["id"], "publishing")
        activate_snapshot(snapshot, repo, settings, client)
    store.publish(job["id"], snapshot, payload["clause_count"], payload["standard_count"], payload["parent"])
    return {"snapshot_id": snapshot, "published": True, "hit_at_5_rate": result["hit_at_5_rate"]}


def execute(job, store, config):
    try:
        if job["kind"] == "parse":
            result = parse_document(job, store, config)
        elif job["kind"] == "publish":
            result = publish_release(job, store, config)
        elif job["kind"] == "assessment":
            from app.portal.assessment import assess
            result = assess(job, store, config)
        elif job["kind"] == "configure_dataset":
            from app.portal.setup import fingerprint
            if job["payload"]["fingerprint"] != fingerprint(config):
                raise DomainError("configuration_changed", "配置已变化，请从向导重新提交空库初始化")
            store.progress(job["id"], "configuring_dataset")
            with DifyClient(config.evidence_settings()) as client:
                detail = client.request("GET", client.path())
                if detail.get("document_count") != 0:
                    raise DomainError("dataset_not_empty", "此功能只配置空白专用知识库，未修改现有数据")
                embedding = {"embedding_model": config.embedding_model, "embedding_model_provider": config.embedding_provider}
                client.request("PATCH", client.path(), json={"indexing_technique": "high_quality", **embedding,
                    "retrieval_model": client.retrieval_model(embedding)})
                client.dataset()
                client.snapshot_metadata()
                result = {"dataset_id": config.dataset_id, "configured": True}
        else:
            raise DomainError("unknown_job", "未知任务类型")
        store.progress(job["id"], "complete", result, status="succeeded")
    except Exception as error:
        current = store.job(job["id"])
        detail = public_error(error, config.secret_values(), stage=current["stage"], request_id=job["id"])
        store.progress(job["id"], current["stage"], status="needs_attention" if detail["code"] in {
            "ambiguous_run", "ambiguous_creation", "sync_locked"} else "failed", error=detail)
        if job["kind"] == "parse":
            doc = store.document(job["payload"]["document_id"])
            store.save_document(doc["id"], doc["revision"], doc["payload"], "failed", "parse_failed", "system:worker")


def main():
    parser = argparse.ArgumentParser(description="本地测试台单任务 worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = PortalSettings.from_env()
    store = PortalRepository(config.db_path)
    store.initialize()
    with worker_lock(config.data_root / "worker.lock"):
        store.recover(include_controls=False)
        stop_heartbeat = threading.Event()
        def heartbeat():
            while not stop_heartbeat.wait(5):
                store.heartbeat()
        threading.Thread(target=heartbeat, daemon=True).start()
        while True:
            store.heartbeat()
            job = store.claim()
            if job:
                execute(job, store, config)
            if args.once:
                stop_heartbeat.set()
                break
            if not job:
                time.sleep(2)


if __name__ == "__main__":
    main()
