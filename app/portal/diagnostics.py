"""页面与 CLI 共用的真实只读诊断；不会调用模型或创建业务证据。"""
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.errors import DomainError
from app.portal.setup import fingerprint
from app.repository import Repository, now
from app.safe_diagnostics import advice, public_error, scrub, upstream_details
from app.settings import ROOT, configured


def input_contract(payload, equipment_type):
    expected = {"images": "file-list", "equipment_type": "select", "equipment_description": "paragraph",
                "operating_state": "select", "work_context": "paragraph", "same_equipment_confirmed": "checkbox",
                "snapshot_id": "text-input"}
    forms = payload.get("user_input_form")
    if not isinstance(forms, list):
        return ["响应缺少 user_input_form"], []
    found, errors, warnings = {}, [], []
    for item in forms:
        if not isinstance(item, dict) or len(item) != 1:
            errors.append("字段定义结构无效")
            continue
        kind, field = next(iter(item.items()))
        if not isinstance(field, dict) or not isinstance(field.get("variable"), str):
            errors.append("字段缺少变量名")
            continue
        name = field["variable"]
        if name in found:
            errors.append("变量名重复：" + name)
        found[name] = (kind, field)
    for name, kind in expected.items():
        if name not in found:
            errors.append("缺少字段：" + name)
        elif found[name][0] != kind:
            errors.append(f"{name} 应为 {kind}，实际为 {found[name][0]}")
    for name, (_, field) in found.items():
        if name not in expected:
            (errors if field.get("required") and field.get("default") in (None, "", []) else warnings).append("额外字段：" + name)
    if "images" in found:
        field = found["images"][1]
        maximum = field.get("max_length")
        if not isinstance(maximum, (int, float)) or maximum < 4:
            errors.append("images 的数量上限须支持 4 张图片")
        if "image" not in field.get("allowed_file_types", []):
            errors.append("images 未允许 image 类型")
        if "local_file" not in field.get("allowed_file_upload_methods", []):
            errors.append("images 未允许 local_file 上传")
        extensions = {v.lower() for v in field.get("allowed_file_extensions", [])}
        if extensions and (".png" not in extensions or not extensions & {".jpg", ".jpeg"}):
            errors.append("images 未同时允许 JPEG 和 PNG")
    for name, limit in (("equipment_description", 4000), ("work_context", 4000), ("snapshot_id", 160)):
        if name in found and found[name][1].get("max_length") is not None and found[name][1]["max_length"] < limit:
            errors.append(f"{name} 的长度上限低于门户契约 {limit}")
    for name, choices in (("equipment_type", {equipment_type}), ("operating_state", {"运行", "停机", "检修", "未知"})):
        if name in found and not choices <= set(found[name][1].get("options", [])):
            errors.append(name + " 缺少门户需要的选项")
    image_limit = payload.get("system_parameters", {}).get("image_file_size_limit")
    if image_limit is not None and image_limit < 5:
        errors.append("Dify 图片文件限制小于 5 MiB")
    return errors, warnings


def parser_version(executable):
    binary = executable.with_name("mineru.exe" if os.name == "nt" else "mineru")
    result = subprocess.run([str(binary), "version", "--json"], capture_output=True, text=True,
        encoding="utf-8", timeout=20, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise DomainError("parse_environment_error", "MinerU 版本命令失败", details={"returncode": result.returncode,
                          "stderr": result.stderr[-3000:]})
    data = json.loads(result.stdout)
    return {key: data.get(key) for key in ("mineru_version", "python_version")}


def run_diagnostics(config, store=None, *, transport=None, version_probe=parser_version, emit=None, active_config=None):
    checks = []
    secret_values = config.secret_values()
    def add(key, title, status, message, *, gates=(), detail=None, suggestion=""):
        item = scrub({"id": key, "title": title, "status": status, "message": message, "gates": list(gates),
                      "details": detail or {}, "suggestion": suggestion if status != "pass" else "", "checked_at": now()}, secret_values)
        checks.append(item)
        if emit:
            emit(item)

    if config.mineru_executable.is_file():
        try:
            version = version_probe(config.mineru_executable)
            ok = version.get("mineru_version") == "4.0.2"
            add("local.mineru", "MinerU 独立环境", "pass" if ok else "fail",
                "解析器版本符合基线" if ok else "需要已验证的 MinerU 4.0.2", gates=["parse"], detail=version)
        except Exception as error:
            add("local.mineru", "MinerU 独立环境", "fail", "无法执行解析器", gates=["parse"], detail=public_error(error, secret_values),
                suggestion="按环境步骤安装独立 .venv-mineru；不要安装到证据服务环境。")
    else:
        add("local.mineru", "MinerU 独立环境", "fail", "找不到 mineru-kit 可执行文件", gates=["parse"],
            suggestion="先运行 deploy/init-portal.ps1 -InstallMinerU，或选择已安装的 MinerU 路径。")
    paths = [("任务库", config.db_path), ("证据库", config.evidence_settings().db_path)]
    for label, path in paths:
        try:
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            add("local." + ("tasks" if label == "任务库" else "evidence"), label, "pass" if version == 1 else "fail",
                "数据库版本正常" if version == 1 else "数据库版本不受支持", gates=["parse", "publish", "assess"])
        except sqlite3.Error:
            add("local." + ("tasks" if label == "任务库" else "evidence"), label, "fail", "数据库尚不可用",
                gates=["parse", "publish", "assess"], suggestion="检查启动诊断及资料目录，不覆盖已有数据库。")
    heartbeat = store.state("worker_heartbeat") if store else ""
    try:
        alive = bool(heartbeat) and (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds() < 30
    except ValueError:
        alive = False
    add("local.worker", "后台任务进程", "pass" if alive else "fail", "worker 心跳正常" if alive else "未检测到近期 worker 心跳",
        gates=["parse", "publish", "assess"], suggestion="运行启动脚本；查看本机服务日志。")

    with httpx.Client(timeout=12, transport=transport, follow_redirects=False) as client:
        def get(path, token, expected=(200,)):
            try:
                response = client.get(path, headers={"Authorization": "Bearer " + token} if token else {})
            except httpx.TimeoutException as error:
                raise DomainError("connection_timeout", "访问服务超时，请检查网络或隧道状态", details={"reason": str(error)}) from error
            except httpx.HTTPError as error:
                raise DomainError("connection_failed", "无法建立服务连接，请检查域名、TLS 或隧道进程", details={"reason": str(error)}) from error
            if response.status_code not in expected:
                raise DomainError("diagnostic_http_error", f"HTTP {response.status_code}", status=502,
                                  details=upstream_details(response, secret_values))
            try:
                data = response.json()
            except ValueError as error:
                raise DomainError("non_json_response", "服务返回的不是 JSON，请核对地址、网关或登录页面") from error
            if not isinstance(data, dict):
                raise DomainError("dify_contract_error", "响应结构不是对象")
            return response.status_code, data

        def failed(key, title, error, gates):
            detail = public_error(error, secret_values)
            add(key, title, "fail", detail["message"], gates=gates, detail=detail.get("details", {}),
                suggestion=advice(detail["code"], detail.get("details")))

        base = config.dify_base_url.rstrip("/")
        if configured(config.knowledge_api_key) and configured(config.dataset_id):
            path = base + "/datasets/" + quote(config.dataset_id, safe="")
            try:
                _, data = get(path, config.knowledge_api_key)
                if data.get("id") != config.dataset_id:
                    raise DomainError("dataset_identity_error", "实际知识库身份与本机配置不一致")
                add("knowledge.auth", "知识库真实鉴权", "pass", "已访问指定知识库", gates=["publish"],
                    detail={"dataset_id": data["id"], "name": data.get("name"), "document_count": data.get("document_count")})
                good = (data.get("indexing_technique") == "high_quality" and data.get("embedding_model") == config.embedding_model
                        and data.get("embedding_model_provider") == config.embedding_provider)
                retrieval = data.get("retrieval_model_dict") or data.get("retrieval_model") or {}
                good = good and retrieval.get("search_method") == "hybrid_search"
                add("knowledge.settings", "索引与嵌入配置", "pass" if good else "fail", "与本机配置一致" if good else "高质量、嵌入模型或混合检索配置不一致",
                    gates=["publish"], detail={"actual_model": data.get("embedding_model"), "expected_model": config.embedding_model,
                        "actual_provider": data.get("embedding_model_provider"), "search_method": retrieval.get("search_method")},
                    suggestion="空库可用向导初始化；已有内容的库需在 Dify 核对配置。")
                _, metadata = get(path + "/metadata", config.knowledge_api_key)
                fields = metadata.get("doc_metadata", [])
                matches = [f for f in fields if f.get("name") == "rag_snapshot_id"] if isinstance(fields, list) else []
                valid = len(matches) == 1 and matches[0].get("type") == "string"
                add("knowledge.metadata", "知识版本元数据", "pass" if valid else ("warn" if not matches else "fail"),
                    "rag_snapshot_id 为字符串字段" if valid else "尚未建立正确的 rag_snapshot_id 字段", gates=["publish"],
                    suggestion="空库初始化或首次同步会创建此字段；错误类型必须先修正。")
                known_ids, pending_names = set(), set()
                if config.evidence_settings().db_path.is_file():
                    with sqlite3.connect(config.evidence_settings().db_path) as conn:
                        known_ids = {row[0] for row in conn.execute("SELECT DISTINCT document_id FROM dify_segments WHERE dataset_id=?", (config.dataset_id,))}
                for manifest_path in (config.data_root / "manifests").glob("sync_*.json"):
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    origin = manifest.get("origin", {})
                    if origin.get("dataset_id") == config.dataset_id and origin.get("base_url") == base:
                        for document in manifest.get("documents", {}).values():
                            if document.get("document_id"):
                                known_ids.add(document["document_id"])
                            elif document.get("name"):
                                pending_names.add(document["name"])
                actual_ids, foreign, used_names = set(), [], set()
                for page in range(1, 101):
                    _, listing = get(path + f"/documents?page={page}&limit=100", config.knowledge_api_key)
                    rows = listing.get("data")
                    if not isinstance(rows, list) or not isinstance(listing.get("has_more"), bool):
                        raise DomainError("dify_contract_error", "文档清单缺少分页字段")
                    for row in rows:
                        identity, name = row.get("id"), row.get("name")
                        if not identity or identity in actual_ids:
                            raise DomainError("dify_contract_error", "文档列表出现无效或重复身份")
                        actual_ids.add(identity)
                        if identity not in known_ids:
                            if name in pending_names and name not in used_names:
                                used_names.add(name)
                            else:
                                foreign.append(identity)
                    if not listing["has_more"]:
                        break
                    if not rows:
                        raise DomainError("dify_contract_error", "文档分页未取得新记录")
                else:
                    raise DomainError("diagnostic_limit", "文档数超过测试版诊断范围，需要单独核查")
                missing = known_ids - actual_ids
                good = not foreign and not missing
                add("knowledge.ownership", "知识库与本机资料归属", "pass" if good else "fail",
                    "远端文档均可在本机登记中定位" if good else "发现未登记文档或已登记文档缺失", gates=["publish", "assess"],
                    detail={"remote_document_count": len(actual_ids), "unknown_document_ids": foreign, "missing_document_ids": sorted(missing)},
                    suggestion="新实例应使用空白专用库；已有实例请核对同步清单，不删除未知文档或绕过映射校验。")
            except Exception as error:
                failed("knowledge.connection", "知识库连接与配置", error, ["publish"])
        else:
            add("knowledge.auth", "知识库真实鉴权", "fail", "尚未填写知识库 ID 和专用密钥", gates=["publish"])

        if configured(config.workflow_api_key):
            try:
                _, info = get(base + "/info", config.workflow_api_key)
                if info.get("mode") != "workflow":
                    raise DomainError("workflow_contract_error", "此密钥对应的应用不是 Workflow")
                add("workflow.auth", "Workflow 真实鉴权", "pass", "应用模式为 Workflow", gates=["assess"], detail={"name": info.get("name"), "mode": info.get("mode")})
                _, params = get(base + "/parameters", config.workflow_api_key)
                equipment = json.loads((ROOT / "config/checklist.json").read_text(encoding="utf-8"))["equipment_type"]
                errors, warnings = input_contract(params, equipment)
                add("workflow.contract", "已发布 Workflow 输入契约", "fail" if errors else "warn" if warnings else "pass",
                    "字段、类型和限额可兼容" if not errors else "已发布工作流输入与门户不兼容", gates=["assess"],
                    detail={"mismatches": errors, "warnings": warnings}, suggestion="下载当前环境 DSL，核对导入目标并发布；不要只修改未发布草稿。")
            except Exception as error:
                failed("workflow.connection", "Workflow API 与输入契约", error, ["assess"])
        else:
            add("workflow.auth", "Workflow 真实鉴权", "fail", "尚未填写 Workflow API 密钥", gates=["assess"])

        for key, url in (("local", config.evidence_local_url), ("https", config.evidence_public_url)):
            title = "本机证据服务" if key == "local" else "本机经 HTTPS 访问证据服务"
            if not url or (key == "https" and not config.readiness()["evidence_https"]):
                add("evidence." + key, title, "fail", "尚未配置有效地址", gates=["assess"])
                continue
            try:
                status, health = get(url.rstrip("/") + "/health", "", (200, 503))
                if not health.get("database") or health.get("status") not in {"ok", "not_ready"}:
                    raise DomainError("evidence_unavailable", "地址未返回预期证据服务健康状态")
                if not configured(config.evidence_api_token):
                    raise DomainError("configuration_error", "证据服务密钥未配置")
                if active_config and config.evidence_api_token != active_config.evidence_api_token:
                    add("evidence." + key, title, "pending", "健康检查通过；草稿中的新密钥尚未应用，鉴权需应用后复检", gates=["assess"],
                        suggestion="应用配置并同步 Dify Secret，重新诊断，再用真实图片验证完整调用。")
                    continue
                # 固定非报告 ID 只做鉴权探测，不查询业务报告、不写上下文。
                _, denied = get(url.rstrip("/") + "/reports/portal-connectivity-probe", config.evidence_api_token, (404,))
                if denied.get("error", {}).get("code") != "report_not_found":
                    raise DomainError("evidence_contract_error", "鉴权探测未返回预期响应")
                add("evidence." + key, title, "pass", "连接与鉴权通过" + ("；空库尚未发布版本，503 属预期" if status == 503 else ""), gates=["assess"])
            except Exception as error:
                failed("evidence." + key, title, error, ["assess"])
    verified = None
    if store:
        for job in store.jobs():
            if job["kind"] == "assessment" and job["status"] == "succeeded" and job["payload"].get("configuration_fingerprint") == fingerprint(config):
                try:
                    report = Repository(config.evidence_settings().db_path).report(job["result"]["report_id"], "trusted-workflow")
                    if report.get("validation_passed") is True and report.get("request", {}).get("request_id") == job["result"].get("run_id"):
                        verified = {"report_id": report["report_id"], "run_id": job["result"]["run_id"], "verified_at": job["updated_at"]}
                        break
                except (DomainError, KeyError, sqlite3.Error):
                    pass
    add("workflow.end_to_end", "Dify 到证据服务及模型链路", "pass" if verified else "pending",
        "此配置曾完成真实报告保存与回读；云端后续改动仍需重新实测" if verified else "需首次真实图片评估并成功回读报告后验证；以上本机诊断不替代此项", detail=verified)
    gates = {stage: not any(c["status"] in {"fail", "pending"} and stage in c["gates"] for c in checks) for stage in ("parse", "publish", "assess")}
    return {"fingerprint": fingerprint(config), "checked_at": now(), "provenance": "synthetic_transport" if transport else "live_read_only_checks",
            "checks": checks, "gates": gates, "all_connections_passed": all(gates.values()), "model_invoked": False}
