"""可嵌入 Dify Code 节点的纯函数，只使用标准库，不做网络或文件操作。"""
import hashlib
import json
import math
import re


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _load(value, label):
    if not isinstance(value, str) or len(value) > 200000:
        raise ValueError(label + " 必须为不超过200000字符的JSON字符串")
    def reject_constant(value):
        raise ValueError("不允许非有限JSON数值")
    try:
        return json.loads(value, parse_constant=reject_constant)
    except (ValueError, TypeError) as error:
        raise ValueError(label + " 不是有效JSON") from error


def _keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(label + " 字段缺失或包含未知字段")


def _model_output(value, label):
    # Dify structured_output 是对象；离线固定响应也允许JSON文本。
    return _load(_dump(value) if isinstance(value, dict) else value, label)


def _text(value, label, maximum=4000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(label + " 文本为空或超限")
    return value


def _id(value, label):
    _text(value, label, 160)
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None:
        raise ValueError(label + " 标识格式不合法")
    return value


def _ids(value, label, minimum=0, maximum=24):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(label + " 数量超限")
    for item in value:
        _id(item, label)
    if len(set(value)) != len(value):
        raise ValueError(label + " 标识重复")
    return value


def _observation_images(values, manifest):
    """只兼容本次清单里可精确定位的文件ID，不猜测未知编号。"""
    allowed = {row["image_id"] for row in manifest}
    aliases = {}
    for row in manifest:
        reference = row["file_ref"]
        if reference in aliases or (reference in allowed and reference != row["image_id"]):
            raise ValueError("图片清单存在歧义，禁止转换图片编号")
        aliases[reference] = row["image_id"]
    normalized = []
    for value in _ids(values, "观察图片", 1, 4):
        identity = value if value in allowed else aliases.get(value)
        if identity is None:
            raise ValueError("视觉观察引用了不存在的图片：" + value)
        normalized.append(identity)
    if len(set(normalized)) != len(normalized):
        raise ValueError("转换后的观察图片标识重复")
    return normalized


def _checklist(value):
    data = _load(value, "checklist")
    if not isinstance(data, dict) or data.get("review_status") != "approved":
        raise ValueError("固定检查清单尚未由业务人员确认")
    _text(data.get("equipment_type"), "试点设备类别", 100)
    _text(data.get("reviewed_by"), "清单确认人", 100)
    _text(data.get("reviewed_at"), "清单确认时间", 100)
    checks = data.get("checks")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 6:
        raise ValueError("固定检查清单必须包含1～6项")
    identifiers = []
    for check in checks:
        _keys(check, ("check_id", "label", "query"), "固定检查项")
        identifiers.append(_id(check["check_id"], "check_id"))
        _text(check["label"], "检查项名称", 200)
        _text(check["query"], "检索问题", 250)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("固定检查项标识重复")
    return data


def validate_input(images, equipment_type, equipment_description, operating_state, work_context,
                   same_equipment_confirmed, workflow_run_id, checklist_json, snapshot_id,
                   dataset_id, workflow_version, model_id):
    checklist = _checklist(checklist_json) if checklist_json is not None else None
    _text(equipment_type, "设备类别", 100)
    if same_equipment_confirmed is not True:
        raise ValueError("必须确认所有图片属于同一台设备")
    if checklist is not None and equipment_type != checklist["equipment_type"]:
        raise ValueError("设备类别不在当前试点范围")
    if operating_state not in ("运行", "停机", "检修", "未知"):
        raise ValueError("工况状态不合法")
    if not isinstance(images, list) or not 1 <= len(images) <= 4:
        raise ValueError("必须提供1～4张图片")
    manifest, references = [], set()
    for index, file in enumerate(images, 1):
        # 原生字段来自固定参考版本 File.to_dict；实际云节点仍需实测采集。
        if not isinstance(file, dict) or file.get("type") != "image" or file.get("transfer_method") != "local_file":
            raise ValueError("只接受通过Dify上传的图片，不接收动态远程URL")
        if file.get("mime_type") not in ("image/jpeg", "image/png"):
            raise ValueError("图片仅允许JPEG、PNG")
        if type(file.get("size")) is not int or not 0 < file["size"] <= 5 * 1024 * 1024:
            raise ValueError("图片大小未知或超过5 MiB")
        reference = _id(file.get("related_id"), "实际上传文件标识")
        if reference in references:
            raise ValueError("不能重复提交同一图片")
        references.add(reference)
        manifest.append({"image_id": f"image_{index:03d}", "position": index, "file_ref": reference})
    request_id = _id(workflow_run_id, "workflow_run_id")
    request = {"request_id": request_id, "snapshot_id": _id(snapshot_id, "snapshot_id"),
               "equipment_id": "equipment_" + hashlib.sha256(request_id.encode()).hexdigest()[:24],
               "image_manifest": manifest, "equipment_type": equipment_type,
               "equipment_description": _text(equipment_description if equipment_description is not None else "", "设备说明", empty=True),
               "operating_state": operating_state, "work_context": _text(work_context, "作业背景", empty=True),
               "same_equipment_confirmed": True, "workflow_version": _text(workflow_version, "工作流版本", 200),
               "model_id": _text(model_id, "模型标识", 200)}
    _id(dataset_id, "dataset_id")
    # 上传UUID只保留在权威请求中，避免模型把file_ref当成image_id。
    model_manifest = [{"image_id": row["image_id"], "position": row["position"]} for row in manifest]
    return {"request_json": _dump(request), "image_manifest_json": _dump(model_manifest),
            "equipment_context_json": _dump({key: request[key] for key in
                ("equipment_type", "equipment_description", "operating_state", "work_context")}),
            "checklist_json": _dump(checklist["checks"] if checklist else [])}


def build_checks(vision_json, request_json, checklist_json):
    vision, request, checklist = _model_output(vision_json, "视觉输出"), _load(request_json, "请求"), _checklist(checklist_json)
    _keys(vision, ("scope_status", "scope_reason", "observations"), "视觉输出")
    _text(vision["scope_reason"], "范围说明")
    if vision["scope_status"] != "same_equipment":
        raise ValueError("图片无法确认同一设备或不可辨认：" + vision["scope_reason"])
    raw = vision["observations"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 18:
        raise ValueError("视觉观察必须包含1～18项")
    image_ids = {item["image_id"] for item in request["image_manifest"]}
    known_checks = {item["check_id"] for item in checklist["checks"]}
    observations, assignments = [], {uid: [] for uid in known_checks}
    for index, item in enumerate(raw, 1):
        _keys(item, ("image_ids", "part", "visible_fact", "unknowns", "check_ids"), "视觉观察")
        normalized_images = _observation_images(item["image_ids"], request["image_manifest"])
        unknown_checks = set(_ids(item["check_ids"], "候选检查项", 0, 6)) - known_checks
        if unknown_checks:
            raise ValueError("视觉观察 obs_" + f"{index:03d}" + " 的check_ids包含清单外检查项：" + ",".join(sorted(unknown_checks)))
        _text(item["part"], "观察部位", 200)
        _text(item["visible_fact"], "可见事实", 3500)
        if not isinstance(item["unknowns"], list) or len(item["unknowns"]) > 20:
            raise ValueError("待确认项数量超限")
        for unknown in item["unknowns"]:
            _text(unknown, "待确认事实")
        uid = f"obs_{index:03d}"
        observations.append({"observation_id": uid, "image_ids": normalized_images,
                             "visible_fact": item["part"] + "：" + item["visible_fact"], "unknowns": item["unknowns"]})
        for check_id in item["check_ids"]:
            assignments[check_id].append(uid)
    checks = []
    for item in checklist["checks"]:
        ids = assignments[item["check_id"]]
        if not ids:
            uid = f"obs_{len(observations) + 1:03d}"
            observations.append({"observation_id": uid, "image_ids": sorted(image_ids),
                "visible_fact": "当前材料不足以确认“" + item["label"] + "”相关状态。",
                "unknowns": ["需补充该部位图片或现场检查；未看见不等于不存在。"]})
            ids = [uid]
        checks.append({"check_id": item["check_id"], "observation_ids": ids, "query": item["query"]})
    request["observations"] = observations
    request["checks"] = checks
    return {"request_json": _dump(request), "observations_json": _dump(observations),
            "checks": [_dump(item) for item in checks], "checks_json": _dump(checks)}


def iteration_query(check_json):
    check = _load(check_json, "检查项")
    _keys(check, ("check_id", "observation_ids", "query"), "检查项")
    return {"query": _text(check["query"], "检索问题", 250)}


def adapt_retrieval(check_json, result, dataset_id):
    check = _load(check_json, "检查项")
    _keys(check, ("check_id", "observation_ids", "query"), "检查项")
    if not isinstance(result, list) or len(result) > 5:
        raise ValueError("Knowledge Retrieval输出必须为Top-5列表；错误不能转换为空列表")
    hits, seen = [], set()
    for item in result:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        if not isinstance(metadata, dict) or metadata.get("dataset_id") != dataset_id:
            raise ValueError("检索命中来自未授权知识库或节点结构不正确")
        hit = {key: _id(metadata.get(key), key) for key in ("dataset_id", "document_id", "segment_id")}
        score = metadata.get("score")
        if type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("检索分数不合法")
        identity = (hit["document_id"], hit["segment_id"])
        if identity in seen:
            continue
        seen.add(identity)
        hits.append({**hit, "score": float(score)})
    return {"check_result_json": _dump({**check, "hits": hits})}


def prepare_payload(request_json, retrieval_results):
    request = _load(request_json, "评估请求")
    if not isinstance(retrieval_results, list) or len(retrieval_results) != len(request["checks"]):
        raise ValueError("检索结果没有覆盖全部检查项")
    results, seen = [], set()
    by_id = {item["check_id"]: item for item in request["checks"]}
    for value in retrieval_results:
        check = _load(value, "逐项检索结果")
        _keys(check, ("check_id", "observation_ids", "query", "hits"), "逐项检索结果")
        uid = check["check_id"]
        if uid not in by_id or uid in seen or {key: check[key] for key in by_id[uid]} != by_id[uid]:
            raise ValueError("检索结果的检查项关联发生变化或重复")
        seen.add(uid)
        results.append(check)
    request["checks"] = sorted(results, key=lambda item: list(by_id).index(item["check_id"]))
    return {"body": _dump(request)}


def _model_evidence(context):
    """保留完整原文及必要上下文，仅移除模型不应选择的内部标识和存档元数据。"""
    clause_fields = ("standard_code", "standard_name", "edition", "standard_status", "scope",
                     "clause_no", "text_verbatim", "evidence_complete")
    evidence = []
    for row in context["evidence"]:
        item = {key: row[key] for key in clause_fields}
        item.update(evidence_id=row["evidence_id"], evidence_complete=row["evidence_complete"],
            applicability_context=row["applicability_context"], completeness_issues=row.get("completeness_issues", []),
            context_clauses=[{key: dependency[key] for key in clause_fields} for dependency in row.get("context_clauses", [])])
        evidence.append(item)
    request_checks = {row["check_id"]: row for row in context["request"]["checks"]}
    checks = [{"check_id": row["check_id"], "observation_ids": request_checks[row["check_id"]]["observation_ids"],
               "retrieval_status": row["retrieval_status"], "allowed_evidence_ids": row["allowed_evidence_ids"]}
              for row in context["checks"]]
    return {"checks": checks, "evidence": evidence}


def _http_failure(label, status_code, body):
    details = []
    try:
        data = _load(body, label)
        error = data.get("error", {}) if isinstance(data, dict) else {}
        if isinstance(error, dict):
            details = [error[key][:500] for key in ("code", "field", "message")
                       if isinstance(error.get(key), str) and error[key]]
    except ValueError:
        pass
    return ValueError(label + "（HTTP " + str(status_code) + "）" + ("：" + "；".join(details) if details else ""))


def unpack_evidence(status_code, body, request_json):
    if status_code != 200:
        raise _http_failure("证据服务未通过校验，停止评估", status_code, body)
    context, request = _load(body, "证据服务响应"), _load(request_json, "原始请求")
    if not isinstance(context, dict) or not isinstance(context.get("request"), dict):
        raise ValueError("证据服务响应缺少请求副本")
    if any(context["request"].get(key) != value for key, value in request.items()):
        raise ValueError("证据上下文与本次请求不匹配")
    _id(context.get("context_id"), "context_id")
    if context.get("snapshot_id") != request["snapshot_id"]:
        raise ValueError("证据快照不一致")
    checks, evidence = context.get("checks"), context.get("evidence")
    if not isinstance(checks, list) or not isinstance(evidence, list):
        raise ValueError("证据响应结构不正确")
    expected = {item["check_id"] for item in request["checks"]}
    if len(checks) != len(expected) or {item["check_id"] for item in checks} != expected:
        raise ValueError("证据响应检查项缺失或重复")
    ids = _ids([item["evidence_id"] for item in evidence], "证据标识", 0, 18)
    for check in checks:
        if check.get("retrieval_status") not in ("matched", "no_match"):
            raise ValueError("技术失败不能作为无命中继续")
        if not set(_ids(check.get("allowed_evidence_ids"), "允许证据", 0, 3)) <= set(ids):
            raise ValueError("允许集合指向不存在的证据")
    return {"context_id": context["context_id"],
            "evidence_json": _dump(_model_evidence(context)),
            "context_json": _dump(context)}


def finalize_payload(context_json, assessment_json):
    context, assessment = _load(context_json, "证据上下文"), _model_output(assessment_json, "模型评估")
    _keys(assessment, ("findings",), "模型评估")
    findings = assessment["findings"]
    checks = {item["check_id"]: item for item in context["checks"]}
    if not isinstance(findings, list) or len(findings) != len(checks):
        raise ValueError("模型评估没有覆盖全部检查项")
    seen = set()
    fields = ("check_id", "observation_ids", "status", "risk_description", "applicability_reason", "evidence_ids", "recommendation", "verification_required")
    for item in findings:
        _keys(item, fields, "finding")
        uid = item["check_id"]
        if uid not in checks or uid in seen:
            raise ValueError("模型评估检查项越界或重复")
        seen.add(uid)
        if (context.get("request", {}).get("workflow_version") or "").startswith("portal-v3-dynamic"):
            for name in ("risk_description", "applicability_reason", "recommendation"):
                _complete_prose(item[name], name)
        unknown_evidence = set(_ids(item["evidence_ids"], "模型证据标识", 0, 3)) - set(checks[uid]["allowed_evidence_ids"])
        if unknown_evidence:
            raise ValueError("检查项 " + uid + " 的evidence_ids包含未授权证据：" + ",".join(sorted(unknown_evidence)))
        if not item["evidence_ids"] and item["status"] != "insufficient_evidence":
            raise ValueError("检查项 " + uid + " 的evidence_ids为空时，status必须为insufficient_evidence")
        prose = _dump([item[key] for key in ("risk_description", "applicability_reason", "recommendation", "verification_required")])
        inline_ids = set(re.findall(r"ev_[0-9a-f]{32}", prose))
        if not inline_ids <= set(item["evidence_ids"]):
            raise ValueError("检查项 " + uid + " 的正文含未列入 evidence_ids 的证据ID")
    # 业务状态、完整性、观察归属等仍由 /reports/finalize 权威校验。
    return {"body": _dump({"context_id": context["context_id"], "findings": findings})}


def unpack_report(status_code, body, context_id):
    if status_code != 200:
        raise _http_failure("定稿校验失败，不得输出模型草稿", status_code, body)
    report = _load(body, "报告响应")
    if (not isinstance(report, dict) or report.get("context_id") != context_id or
        report.get("validation_passed") is not True or report.get("review_status") != "pending_review"):
        raise ValueError("报告身份或校验状态不正确")
    _id(report.get("report_id"), "report_id")
    _text(report.get("markdown"), "报告Markdown", 200000)
    return {"report_id": report["report_id"], "markdown": report["markdown"],
            "validation_json": _dump(report["validation"])}


# Portal v3: dynamic questions; legacy candidate workflows retain their original contract.
def validate_dynamic_input(images, equipment_type, equipment_description, operating_state, work_context,
                           same_equipment_confirmed, workflow_run_id, snapshot_id, dataset_id,
                           workflow_version, model_id, user_question):
    _text(equipment_type, "设备类别", 100)
    _text(user_question, "用户问题", 4000)
    # Reuse file identity and operating-state validation without a fixed checklist.
    result = validate_input(images, equipment_type, equipment_description, operating_state, work_context,
                            same_equipment_confirmed, workflow_run_id, None, snapshot_id,
                            dataset_id, workflow_version, model_id)
    request = _load(result["request_json"], "请求")
    request["user_question"] = user_question
    result["request_json"] = _dump(request)
    context = _load(result["equipment_context_json"], "设备说明")
    context["user_question"] = user_question
    result["equipment_context_json"] = _dump(context)
    return {key: result[key] for key in ("request_json", "image_manifest_json", "equipment_context_json")}


def _complete_prose(value, label, maximum=4000):
    text = _text(value, label, maximum)
    if len(re.sub(r"\s", "", text)) < 8 or len(set(text.strip())) < 4:
        raise ValueError(label + " 输出残缺，请查看模型原始输出及结构化输出；禁止保存无意义短文本")
    return text


def build_dynamic_checks(vision_json, request_json):
    vision, request = _model_output(vision_json, "动态视觉输出"), _load(request_json, "请求")
    _keys(vision, ("scope_status", "scope_reason", "observations", "checks"), "动态视觉输出")
    _text(vision["scope_reason"], "范围说明")
    if vision["scope_status"] != "same_equipment":
        raise ValueError("图片无法确认同一设备或不可辨认：" + vision["scope_reason"])
    raw, plan = vision["observations"], vision["checks"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 18:
        raise ValueError("视觉观察必须包含1～18项")
    if not isinstance(plan, list) or not 1 <= len(plan) <= 6:
        raise ValueError("动态检索计划必须包含1～6项")
    observations = []
    for index, item in enumerate(raw, 1):
        _keys(item, ("image_ids", "part", "visible_fact", "unknowns"), "视觉观察")
        images = _observation_images(item["image_ids"], request["image_manifest"])
        _text(item["part"], "观察部位", 200)
        _complete_prose(item["visible_fact"], "可见事实", 3500)
        if not isinstance(item["unknowns"], list) or len(item["unknowns"]) > 20:
            raise ValueError("待确认事实数量无效")
        for unknown in item["unknowns"]:
            _text(unknown, "待确认事实")
        observations.append({"observation_id": f"obs_{index:03d}", "image_ids": images,
                             "visible_fact": item["part"] + "：" + item["visible_fact"], "unknowns": item["unknowns"]})
    checks, seen = [], set()
    for index, item in enumerate(plan, 1):
        _keys(item, ("observation_indices", "query"), "动态检索方向")
        indices = item["observation_indices"]
        if (not isinstance(indices, list) or not 1 <= len(indices) <= 18
            or any(type(n) is not int or not 1 <= n <= len(observations) for n in indices)
            or len(set(indices)) != len(indices)):
            raise ValueError("动态检查项必须关联本次真实观察序号")
        query = _complete_prose(item["query"], "检索问题", 250).strip()
        normalized = re.sub(r"\s", "", query)
        if normalized in seen:
            raise ValueError("动态检索问题重复")
        seen.add(normalized)
        checks.append({"check_id": f"check_{index:03d}",
                       "observation_ids": [f"obs_{n:03d}" for n in indices], "query": query})
    request["observations"], request["checks"] = observations, checks
    return {"request_json": _dump(request), "observations_json": _dump(observations),
            "checks": [_dump(item) for item in checks], "checks_json": _dump(checks)}
