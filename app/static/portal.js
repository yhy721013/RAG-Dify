"use strict";
const $ = (selector) => document.querySelector(selector);
let csrf = "",
  currentDoc = null,
  releasePreview = null,
  selectedCandidate = "",
  view = "library";
let submissionId = crypto.randomUUID();
let lastStatus = null,
  documentsData = [],
  selectedImages = [],
  imageUrls = [],
  reviewOptions = [],
  caseRows = [];
let lastErrorSignature = "";
let lastDocuments = "",
  lastJobs = "",
  lastReleases = "";
const labels = {
  queued: "等待处理",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败",
  interrupted: "已中断",
  needs_attention: "需要对账",
  pending_review: "待人工复核",
  approved: "已批准",
  pending: "待复核",
};
const stages = {
  queued: "已排队",
  parsing: "MinerU 解析",
  candidates: "整理候选条款",
  importing: "导入已批准条款",
  indexing: "建立及核对索引",
  evaluation: "检索自检",
  publishing: "发布知识版本",
  uploading: "上传设备图片",
  workflow: "Dify 工作流",
  reconciling: "核对远程运行",
  report: "核对保存报告",
  complete: "已完成",
  diagnosing: "实际连接诊断",
  diagnostic_check: "诊断检查项",
  workflow_node: "Dify 节点",
  configuring_dataset: "初始化空知识库",
  tunnel: "临时 HTTPS 隧道",
};
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function message(text, error = false) {
  const node = $("#message");
  node.textContent = text;
  node.className = error ? "error" : "";
  node.hidden = false;
  if (!error) lastErrorSignature = "";
}
function displayError(error) {
  const detail = error.info || error;
  const signature = (detail.code || "") + ":" + (detail.message || "请求失败");
  if (lastErrorSignature === signature && !$("#message").hidden) return;
  message(detail.message || "请求失败，请查看详情", true);
  lastErrorSignature = signature;
  const node = $("#message");
  if (detail.suggestion) node.append(element("p", detail.suggestion));
  const more = element("details");
  more.append(
    element("summary", "排查详情"),
    element("pre", JSON.stringify(detail, null, 2)),
  );
  node.append(more);
  if (detail.code === "network_error") {
    $("#readiness").textContent =
      "与本机服务连接中断，当前任务状态未确认；页面显示的是上次取得的信息。";
    $("#readiness").classList.add("warning");
  }
  for (const input of document.querySelectorAll(".field-error"))
    input.classList.remove("field-error");
  const fields = [...(detail.details?.fields || detail.fields || [])];
  if (detail.field) fields.push({ field: detail.field });
  for (const item of fields)
    for (const input of document.querySelectorAll("input,textarea,select")) {
      if (
        input.name === item.field.split(".").pop() ||
        input.dataset.configField === item.field.split(".").pop()
      )
        input.classList.add("field-error");
    }
}
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET")
    headers["X-CSRF-Token"] = csrf;
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 30000);
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (failure) {
    const error = new Error("无法连接本机服务，或等待响应超时");
    error.info = {
      code: "network_error",
      message: error.message,
      suggestion:
        "检查启动脚本和本机服务日志。已提交操作的结果可能未返回，先查看任务记录再重试。",
    };
    throw error;
  } finally {
    clearTimeout(timer);
  }
  let data;
  try {
    data = await response.json();
  } catch (failure) {
    const error = new Error(`服务返回非 JSON 响应（HTTP ${response.status}）`);
    error.info = {
      code: "non_json_response",
      message: error.message,
      request_id: response.headers.get("X-Request-ID"),
    };
    throw error;
  }
  if (!response.ok) {
    const error = new Error(data.error?.message || data.detail || "请求失败");
    error.info = {
      ...(data.error || {}),
      message: error.message,
      http_status: response.status,
      request_id:
        data.error?.request_id || response.headers.get("X-Request-ID"),
    };
    throw error;
  }
  return data;
}
function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
async function run(action, button) {
  if (button) button.disabled = true;
  try {
    await action();
  } catch (error) {
    displayError(error);
  } finally {
    if (button) button.disabled = false;
  }
}
function show(name) {
  if (
    view === "setup" &&
    name !== "setup" &&
    window.setupUI?.isDirty() &&
    !confirm("配置有未保存修改，离开将丢失。确定离开？")
  )
    return;
  if (
    view === "review" &&
    name !== "review" &&
    reviewDirty() &&
    !confirm("有未保存的复核修改。离开后可能丢失，确定离开？")
  )
    return;
  view = name;
  for (const node of document.querySelectorAll(".view"))
    node.hidden = node.id !== name + "-view";
  for (const node of document.querySelectorAll("nav button"))
    node.classList.toggle("active", node.dataset.view === name);
  $("#page-title").textContent = {
    library: "标准资料库",
    review: "条款人工复核",
    assessment: "设备评估",
    jobs: "任务与报告",
    setup: "首次配置与诊断",
  }[name];
  $("#first-test-guide").hidden = name === "review" || name === "setup";
  if (name === "setup" && window.setupUI) run(window.setupUI.load);
}
async function status() {
  const data = await api("/api/status");
  lastStatus = data;
  csrf = data.csrf_token;
  const names = {
    mineru: "MinerU",
    knowledge: "知识库密钥/ID",
    workflow: "Workflow API 密钥",
    evidence_token: "证据服务密钥",
    evidence_https: "证据服务 HTTPS",
  };
  const missing = Object.entries(data.configured)
    .filter(([, ok]) => !ok)
    .map(([key]) => names[key]);
  const heartbeat = data.worker_heartbeat
    ? Date.parse(data.worker_heartbeat)
    : 0;
  const alive = Date.now() - heartbeat < 30000;
  $("#readiness").textContent =
    (missing.length
      ? "待配置：" + missing.join("、") + "。打开“首次配置与诊断”逐步处理。"
      : "配置已填写，实际检查结果见首次配置与诊断。") +
    (alive ? " 后台任务进程在线。" : " 后台任务进程未就绪，请运行启动脚本。");
  $("#readiness").classList.toggle("warning", missing.length > 0 || !alive);
  $("#upload-limit").textContent =
    `PDF · 最高 ${Math.round(data.max_pdf_bytes / 1048576)} MiB / ${data.max_pdf_pages} 页 · 每次一份`;
  $("#assessment-version").textContent = data.current_snapshot
    ? "本次将使用已发布知识版本：" + data.current_snapshot
    : "请先完成标准复核并发布知识版本。";
  if (data.configuration_error)
    $("#readiness").textContent = data.configuration_error;
  const diagnostic = data.diagnostics;
  const failedChecks =
    diagnostic && !diagnostic.stale
      ? diagnostic.checks.filter(
          (c) => c.status === "fail" && c.gates.includes("assess"),
        )
      : [];
  $("#assessment-prerequisites").textContent = !data.current_snapshot
    ? "下一步：先复核条款并发布知识版本。"
    : failedChecks.length
      ? "评估前需处理：" + failedChecks.map((c) => c.title).join("、")
      : "准备好图片和工况后即可发起真实评估；会调用已配置的模型。";
  const button = $("#assessment-form button[type=submit]");
  if (button)
    button.disabled =
      !data.current_snapshot ||
      missing.some((k) => k !== "MinerU") ||
      failedChecks.length > 0 ||
      !alive ||
      data.maintenance;
  $("#assessment-checklist").replaceChildren(
    ...(data.checklist || []).map((c) => element("p", c.label)),
  );
  renderGuide();
}
async function refreshDocuments() {
  const rows = await api("/api/documents"),
    root = $("#documents");
  const signature = JSON.stringify(rows);
  documentsData = rows;
  renderGuide();
  if (signature === lastDocuments) return;
  lastDocuments = signature;
  const chosen = new Set(
    [...root.querySelectorAll("input:checked")].map((n) => n.value),
  );
  root.replaceChildren();
  if (!rows.length) {
    root.textContent = "尚未上传标准。";
    return;
  }
  for (const row of rows) {
    const line = element("div", undefined, "doc-row"),
      check = element("input");
    check.type = "checkbox";
    check.value = row.id;
    check.checked = chosen.has(row.id);
    line.append(check);
    const info = element("div", undefined, "row-main");
    info.append(
      element("strong", row.filename),
      element(
        "div",
        `${row.page_count} 页 · ${row.approved_count} / ${row.candidate_count} 条已批准 · ${labels[row.status] || row.status}`,
        "meta",
      ),
    );
    line.append(info);
    const button = element("button", "对照复核", "secondary");
    button.disabled = !row.candidate_count;
    button.addEventListener("click", () =>
      run(() => openDocument(row.id), button),
    );
    line.append(button);
    const task = element("button", "查看处理与报错", "secondary");
    task.addEventListener("click", () => {
      show("jobs");
      run(async () => {
        await refreshJobs();
        const row = [...document.querySelectorAll(".job-row")].find(
          (n) => n.dataset.documentId === rowId,
        );
        if (row) row.scrollIntoView({ behavior: "smooth" });
      });
    });
    const rowId = row.id;
    line.append(task);
    root.append(line);
  }
}
async function refreshReleases() {
  const data = await api("/api/releases"),
    root = $("#releases");
  const signature = JSON.stringify(data);
  if (signature === lastReleases) return;
  lastReleases = signature;
  root.replaceChildren();
  if (!data.releases.length) {
    root.textContent = "尚无已发布版本。";
    return;
  }
  for (const row of data.releases) {
    const line = element("div", undefined, "release-row");
    line.append(
      element("strong", row.snapshot_id),
      element(
        "span",
        `${row.standard_count} 份标准 / ${row.clause_count} 条款`,
        "meta",
      ),
    );
    if (row.snapshot_id === data.current_snapshot)
      line.append(element("span", "当前版本", "tag ok"));
    root.append(line);
  }
}
async function refreshJobs() {
  const rows = await api("/api/jobs"),
    root = $("#jobs");
  const signature = JSON.stringify(rows);
  if (signature === lastJobs) return;
  lastJobs = signature;
  root.replaceChildren();
  if (!rows.length) {
    root.textContent = "暂无任务。";
    return;
  }
  for (const row of rows) {
    const line = element("div", undefined, "job-row"),
      info = element("div", undefined, "row-main");
    info.append(
      element(
        "strong",
        {
          parse: "标准解析",
          publish: "知识版本发布",
          assessment: "设备评估",
          diagnostics: "连接诊断",
          configure_dataset: "空库初始化",
          tunnel: "临时隧道",
        }[row.kind] +
          " · " +
          (stages[row.stage] || row.stage),
      ),
      element(
        "div",
        row.id + " · " + new Date(row.created_at).toLocaleString(),
        "meta",
      ),
    );
    line.dataset.jobId = row.id;
    if (row.document_id) line.dataset.documentId = row.document_id;
    if (row.title) info.prepend(element("strong", row.title));
    if (row.result?.run_id)
      info.append(element("div", "Dify 运行：" + row.result.run_id, "meta"));
    if (row.error?.message)
      info.append(element("div", row.error.message, "meta"));
    if (row.error?.suggestion)
      info.append(element("p", row.error.suggestion, "hint"));
    if (row.kind === "diagnostics" && row.result?.checks)
      info.append(
        element(
          "p",
          `诊断结果：${row.result.checks.filter((c) => c.status === "fail").length} 项未通过；模型未调用。`,
          "hint",
        ),
      );
    const history = element("details"),
      historyText = element("pre");
    history.append(element("summary", "执行记录"), historyText);
    history.addEventListener("toggle", () => {
      if (history.open)
        run(async () => {
          const detail = await api(`/api/jobs/${row.id}`);
          historyText.textContent = detail.events.length
            ? detail.events
                .map(
                  (e) =>
                    `${new Date(e.created_at).toLocaleString()} · ${stages[e.stage] || e.stage} · ${labels[e.status] || e.status}${e.error.message ? " · " + e.error.message : ""}`,
                )
                .join("\n")
            : "此任务在阶段历史记录功能加入前已完成。";
        });
    });
    info.append(history);
    line.append(
      info,
      element(
        "span",
        labels[row.status] || row.status,
        "tag " +
          (row.status === "succeeded"
            ? "ok"
            : ["failed", "interrupted", "needs_attention"].includes(row.status)
              ? "fail"
              : ""),
      ),
    );
    if (row.status === "succeeded" && row.kind === "assessment") {
      const b = element("button", "查看报告", "secondary");
      b.addEventListener("click", () => run(() => openReport(row.id), b));
      line.append(b);
    }
    if (
      ["failed", "interrupted", "needs_attention"].includes(row.status) &&
      row.kind !== "diagnostics"
    ) {
      const b = element("button", "恢复 / 对账", "secondary");
      b.addEventListener("click", () =>
        run(async () => {
          await post(`/api/jobs/${row.id}/retry`, {});
          await refreshJobs();
        }, b),
      );
      line.append(b);
    }
    const inspect = element("button", "查看诊断与日志", "secondary");
    inspect.addEventListener("click", () =>
      run(() => openTaskDiagnostics(row.id), inspect),
    );
    line.append(inspect);
    root.append(line);
  }
}
async function openReport(id) {
  $("#report-panel").hidden = true;
  $("#task-diagnostics-panel").hidden = true;
  const report = await api(`/api/jobs/${id}/report`);
  $("#report-text").textContent = report.markdown;
  renderReport(report);
  $("#download-md").href = `/api/jobs/${id}/report/md`;
  $("#download-json").href = `/api/jobs/${id}/report/json`;
  $("#report-panel").hidden = false;
  $("#report-panel").scrollIntoView({ behavior: "smooth" });
}
const metadataNames = {
  standard_code: "标准号",
  standard_name: "标准完整名称",
  edition: "版本",
  scope: "标准适用范围",
  standard_status: "标准状态（现行/废止等）",
  status_verified_at: "状态核验日期（YYYY-MM-DD）",
  status_source: "状态核验来源（网址或可核查出处）",
};
function fillDocument(doc, selection) {
  currentDoc = {
    ...doc,
    asset_links: doc.asset_links || currentDoc?.asset_links || {},
  };
  $("#review-title").textContent = doc.filename;
  const root = $("#metadata-fields");
  root.replaceChildren();
  for (const [key, title] of Object.entries(metadataNames)) {
    const label = element("label", title),
      input = element(key === "scope" ? "textarea" : "input");
    input.name = key;
    input.value =
      doc.payload.metadata?.[key] ||
      doc.payload.candidates[0]?.record[key] ||
      "";
    input.required = true;
    label.append(input);
    root.append(label);
  }
  const select = $("#candidate-select");
  select.replaceChildren();
  for (const item of doc.payload.candidates) {
    const option = element(
      "option",
      `${item.record.clause_no} · ${labels[item.record.content_review_status] || item.record.content_review_status}`,
    );
    option.value = item.id;
    select.append(option);
  }
  select.value = doc.payload.candidates.some((i) => i.id === selection)
    ? selection
    : doc.payload.candidates[0]?.id;
  fillCandidate();
  renderCandidateFilter(selection);
}
async function openDocument(id) {
  const doc = await api(`/api/documents/${id}`);
  reviewOptions = await api(
    "/api/review/options?document_id=" + encodeURIComponent(id),
  );
  $("#source-download").href = `/api/documents/${id}/pdf`;
  $("#pdf-page-number").max = doc.page_count;
  fillDocument(doc);
  show("review");
}
function fillCandidate() {
  selectedCandidate = $("#candidate-select").value;
  const item = currentDoc.payload.candidates.find(
    (i) => i.id === selectedCandidate,
  );
  if (!item) return;
  const record = item.record;
  $("#clause-no").value = record.clause_no;
  $("#clause-path").value = record.clause_path.join(" / ");
  $("#clause-text").value = record.text_verbatim;
  $("#source-blocks").value = record.source_spans
    .flatMap((s) => s.block_ids)
    .join(", ");
  $("#context-uids").value = record.context_clause_uids.join(", ");
  $("#review-notes").value = record.review_notes || "";
  $("#candidate-info").textContent =
    `${labels[record.content_review_status]} · UID: ${record.clause_uid || "保存标准信息后生成"}\n待核查：${record.review_issues.join("、") || "无"}`;
  for (const checkbox of document.querySelectorAll("#acknowledgements input"))
    checkbox.checked = false;
  const first = record.source_spans[0];
  if (first) showPage(first.pdf_page_index + 1);
  renderSourceOptions();
  renderContextOptions();
}
function actor() {
  const value = $("#review-actor").value.trim();
  if (!value) throw new Error("请填写实际人工复核人");
  return value;
}
function listValue(id) {
  return $(id)
    .value.split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
}
async function candidateAction(action, extra = {}) {
  if (action !== "edit") ensureSavedReview();
  const doc = await post(
    `/api/documents/${currentDoc.id}/candidates/${selectedCandidate}/${action}`,
    { revision: currentDoc.revision, actor: actor(), ...extra },
  );
  fillDocument(doc, selectedCandidate);
  message(
    action === "approve"
      ? "当前条款已记录人工批准。发布前仍将核验依赖完整性。"
      : "修改已保存，受影响条款需要重新复核。 ",
  );
}
for (const button of document.querySelectorAll("nav button"))
  button.addEventListener("click", () => {
    show(button.dataset.view);
    run(refresh);
  });
$("#back-library").addEventListener("click", () => {
  show("library");
  run(refresh);
});
$("#refresh").addEventListener("click", () => run(refresh, $("#refresh")));
$("#candidate-select").addEventListener("change", () => {
  if (candidateDirty()) {
    $("#candidate-select").value = selectedCandidate;
    message("当前条款有未保存修改，请先保存后再切换。", true);
    return;
  }
  fillCandidate();
});
$("#upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async () => {
    const body = new FormData();
    body.append("file", $("#pdf-file").files[0]);
    const result = await api("/api/documents", { method: "POST", body });
    message(
      result.reused
        ? "文件已存在，已复用已有解析任务与复核记录。"
        : "上传成功，后台将自动解析。可在任务页查看进度。",
    );
    await refresh();
  }, event.submitter);
});
$("#metadata-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async () => {
    const metadata = Object.fromEntries(
      [...document.querySelectorAll("#metadata-fields [name]")].map((n) => [
        n.name,
        n.value,
      ]),
    );
    const doc = await post(`/api/documents/${currentDoc.id}/metadata`, {
      revision: currentDoc.revision,
      actor: actor(),
      metadata,
    });
    fillDocument(doc, selectedCandidate);
    message("标准信息已保存；发生变化的条款须重新复核。");
  }, event.submitter);
});
$("#candidate-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(
    () =>
      candidateAction("edit", {
        changes: {
          text_verbatim: $("#clause-text").value,
          clause_no: $("#clause-no").value,
          clause_path: $("#clause-path")
            .value.split("/")
            .map((x) => x.trim())
            .filter(Boolean),
          context_clause_uids: listValue("#context-uids"),
          review_notes: $("#review-notes").value,
        },
        block_ids: listValue("#source-blocks"),
      }),
    event.submitter,
  );
});
$("#approve-clause").addEventListener("click", () =>
  run(
    () =>
      candidateAction("approve", {
        acknowledgements: [
          ...document.querySelectorAll("#acknowledgements input:checked"),
        ].map((n) => n.value),
      }),
    $("#approve-clause"),
  ),
);
$("#split-clause").addEventListener("click", () =>
  run(
    () =>
      candidateAction("split", { offset: $("#clause-text").selectionStart }),
    $("#split-clause"),
  ),
);
$("#merge-clause").addEventListener("click", () =>
  run(async () => {
    const items = currentDoc.payload.candidates,
      index = items.findIndex((i) => i.id === selectedCandidate);
    if (!items[index + 1]) throw new Error("已是最后一个候选");
    if (!confirm("合并当前与下一候选？合并后须重新核对条款号、来源及依赖。"))
      return;
    await candidateAction("merge", { candidate_ids: [items[index + 1].id] });
  }, $("#merge-clause")),
);
$("#preview-release").addEventListener("click", () =>
  run(async () => {
    const ids = [...document.querySelectorAll("#documents input:checked")].map(
      (n) => n.value,
    );
    if (!ids.length) throw new Error("请先勾选标准文件");
    releasePreview = await post("/api/releases/preview", { document_ids: ids });
    $("#release-summary").textContent =
      `基础版本：${releasePreview.parent || "空库"}\n本次形成：${releasePreview.standard_count} 份标准 / ${releasePreview.clause_count} 条已批准条款\n未纳入的待复核条款：${releasePreview.pending_count}\n被替换的同标准版本：${releasePreview.replacements.join(", ") || "无"}`;
    $("#release-clauses").textContent = releasePreview.records
      .map(
        (r) =>
          `${r.standard_code} §${r.clause_no}  ${r.clause_uid}\n${r.text_verbatim.slice(0, 180)}`,
      )
      .join("\n\n");
    $("#publish-release").disabled =
      releasePreview.unchanged || !!releasePreview.blockers?.length;
    if (releasePreview.unchanged)
      $("#release-summary").textContent +=
        "\n已批准内容没有变化，无需重复发布。";
    renderReleaseEditor();
    $("#release-panel").hidden = false;
    $("#confirm-replace").checked = false;
    $("#release-panel").scrollIntoView({ behavior: "smooth" });
  }, $("#preview-release")),
);
$("#publish-release").addEventListener("click", () =>
  run(async () => {
    if (!releasePreview) throw new Error("请先预览版本");
    const job = await post("/api/releases", {
      document_ids: Object.keys(releasePreview.document_revisions),
      preview_hash: releasePreview.preview_hash,
      confirm_replacements: $("#confirm-replace").checked,
      actor: $("#release-actor").value,
      cases: collectCases(),
    });
    message("已提交发布任务：" + job.id);
    show("jobs");
    await refresh();
  }, $("#publish-release")),
);
$("#assessment-form").addEventListener("submit", (event) => {
  event.preventDefault();
  run(async () => {
    const body = new FormData(event.target);
    body.delete("same_equipment_confirmed");
    body.append("same_equipment_confirmed", "true");
    body.append("submission_id", submissionId);
    for (const file of selectedImages) body.append("images", file);
    if (!selectedImages.length) throw new Error("请先选择设备图片");
    const job = await api("/api/assessments", { method: "POST", body });
    submissionId = crypto.randomUUID();
    message("评估已提交：" + job.id);
    $("#report-panel").hidden = true;
    show("jobs");
    await refresh();
  }, event.submitter);
});
async function refresh() {
  await Promise.all([
    status(),
    refreshDocuments(),
    refreshReleases(),
    refreshJobs(),
  ]);
}
run(refresh);
setInterval(() => {
  if (view !== "review") run(refresh);
}, 5000);

function showPage(number) {
  const page = Math.max(
    1,
    Math.min(currentDoc.page_count, Number(number) || 1),
  );
  $("#pdf-page-number").value = page;
  $("#source-pdf").src = `/api/documents/${currentDoc.id}/pages/${page}`;
}
$("#previous-page").addEventListener("click", () =>
  showPage(Number($("#pdf-page-number").value) - 1),
);
$("#next-page").addEventListener("click", () =>
  showPage(Number($("#pdf-page-number").value) + 1),
);
$("#pdf-page-number").addEventListener("change", () =>
  showPage($("#pdf-page-number").value),
);

function renderReport(report) {
  const root = $("#report-cards");
  root.replaceChildren();
  root.append(
    element(
      "p",
      `知识版本 ${report.snapshot_id} · ${report.findings.length} 项检查 · ${new Date(report.created_at).toLocaleString()}`,
      "meta",
    ),
  );
  const observations = new Map(
    report.request.observations.map((row) => [row.observation_id, row]),
  );
  const states = {
    evidence_supported_risk: "有证据支持的风险",
    needs_confirmation: "需现场确认",
    insufficient_evidence: "证据不足",
  };
  for (const [index, finding] of report.findings.entries()) {
    const section = element("section", undefined, "finding");
    section.append(
      element(
        "h3",
        `${index + 1}. ${lastStatus?.checklist?.find((c) => c.check_id === finding.check_id)?.label || finding.check_id} · ${states[finding.status] || finding.status}`,
      ),
    );
    section.append(element("p", finding.risk_description));
    section.append(element("h4", "可见事实"));
    for (const id of finding.observation_ids) {
      const row = observations.get(id);
      if (row) {
        section.append(element("p", row.visible_fact));
        if (row.unknowns.length)
          section.append(
            element("p", "未知信息：" + row.unknowns.join("；"), "hint"),
          );
      }
    }
    section.append(
      element("h4", "适用条件"),
      element("p", finding.applicability_reason),
    );
    const citations = element("details");
    citations.append(
      element("summary", `标准依据（${finding.citations.length} 条）`),
    );
    for (const citation of finding.citations) {
      const block = element("blockquote");
      block.append(
        element(
          "strong",
          `${citation.standard_code} ${citation.standard_name} · ${citation.clause_no}`,
        ),
        element("pre", citation.text_verbatim),
        element(
          "p",
          "PDF 页：" +
            [
              ...new Set(
                citation.source_spans.map((s) => s.pdf_page_index + 1),
              ),
            ].join("、"),
          "meta",
        ),
      );
      for (const dependency of citation.context_clauses || []) {
        const context = element("details");
        context.append(
          element("summary", "必要上下文 · " + dependency.clause_no),
          element("pre", dependency.text_verbatim),
        );
        block.append(context);
      }
      citations.append(block);
    }
    section.append(
      citations,
      element("h4", "建议与待确认事项"),
      element("p", finding.recommendation),
    );
    if (finding.verification_required.length) {
      const list = element("ul");
      for (const text of finding.verification_required)
        list.append(element("li", text));
      section.append(list);
    }
    root.append(section);
  }
}

function candidateDirty() {
  const record = currentDoc?.payload.candidates.find(
    (row) => row.id === selectedCandidate,
  )?.record;
  if (!record) return false;
  return (
    $("#clause-text").value !== record.text_verbatim ||
    $("#clause-no").value !== record.clause_no ||
    JSON.stringify(
      $("#clause-path")
        .value.split("/")
        .map((x) => x.trim())
        .filter(Boolean),
    ) !== JSON.stringify(record.clause_path) ||
    JSON.stringify(listValue("#source-blocks")) !==
      JSON.stringify(record.source_spans.flatMap((s) => s.block_ids)) ||
    JSON.stringify(listValue("#context-uids")) !==
      JSON.stringify(record.context_clause_uids) ||
    $("#review-notes").value !== (record.review_notes || "")
  );
}
function ensureSavedReview() {
  const record = currentDoc.payload.candidates.find(
    (row) => row.id === selectedCandidate,
  ).record;
  const metadataDirty = [
    ...document.querySelectorAll("#metadata-fields [name]"),
  ].some(
    (n) =>
      n.value !==
      (currentDoc.payload.metadata?.[n.name] || record[n.name] || ""),
  );
  if (candidateDirty() || metadataDirty)
    throw new Error("存在未保存的条款或标准信息，请先保存，再批准或调整边界。");
}

function renderGuide() {
  if (!lastStatus) return;
  const parsed = documentsData.some((d) => d.candidate_count),
    approved = documentsData.some((d) => d.approved_count);
  const steps = [
    [
      "1. 配置与实际诊断",
      "按向导连接自己的知识库、HTTPS 和 Workflow。",
      "setup",
      Object.values(lastStatus.configured).every(Boolean),
    ],
    [
      "2. 上传标准 PDF",
      "自动完整解析；失败原因在任务诊断中可见。",
      "library",
      parsed,
    ],
    [
      "3. 对照原文复核",
      "填写标准身份，确认条款、来源及依赖。",
      "library",
      approved,
    ],
    [
      "4. 检索自检与发布",
      "选择目标条款并填写问题，核验通过才更新知识库。",
      "library",
      !!lastStatus.current_snapshot,
    ],
    [
      "5. 自备图片与工况",
      "仅同一台普通卧式金属车床；不确定信息填未知。",
      "assessment",
      false,
    ],
  ];
  const root = $("#guide-steps");
  root.replaceChildren();
  for (const [title, text, target, done] of steps) {
    const card = element("div", undefined, "guide-step");
    card.append(element("strong", title), element("p", text));
    const button = element(
      "button",
      done ? "查看 / 继续" : "前往",
      "secondary",
    );
    button.type = "button";
    button.addEventListener("click", () => show(target));
    card.append(button);
    root.append(card);
  }
}

function renderCandidateFilter(preferred = selectedCandidate) {
  if (!currentDoc) return;
  const filter = $("#candidate-filter").value,
    query = $("#candidate-search").value.trim().toLowerCase();
  const rows = currentDoc.payload.candidates.filter((item) => {
    const r = item.record,
      issues = r.review_issues.join(" ");
    return (
      (!query ||
        (r.clause_no + " " + r.text_verbatim).toLowerCase().includes(query)) &&
      (filter === "all" ||
        (filter === "pending" && r.content_review_status !== "approved") ||
        (filter === "approved" && r.content_review_status === "approved") ||
        (filter === "boundary" && r.boundary_status !== "confirmed") ||
        (filter === "assets" && /asset|figure|table/.test(issues)))
    );
  });
  const select = $("#candidate-select");
  select.replaceChildren();
  for (const item of rows) {
    const option = element(
      "option",
      `${item.record.clause_no} · ${labels[item.record.content_review_status]}`,
    );
    option.value = item.id;
    select.append(option);
  }
  $("#candidate-count").textContent =
    `显示 ${rows.length} / ${currentDoc.payload.candidates.length} 个候选。机器识别的边界和原文仍需逐项核对。`;
  if (rows.length) {
    select.value = rows.some((r) => r.id === preferred)
      ? preferred
      : rows[0].id;
    fillCandidate();
  } else selectedCandidate = "";
  $("#candidate-form").hidden = !rows.length;
  $("#acknowledgements").hidden = !rows.length;
  $("#approve-clause").disabled = !rows.length;
  $("#split-clause").disabled = !rows.length;
  $("#merge-clause").disabled = !rows.length;
}
for (const id of ["candidate-filter", "candidate-search"])
  $("#" + id).addEventListener(
    id === "candidate-search" ? "input" : "change",
    () => {
      if (reviewDirty()) {
        message("有未保存的修改，请先保存后再筛选。", true);
        return;
      }
      renderCandidateFilter();
    },
  );

function renderSourceOptions() {
  if (!currentDoc) return;
  const selected = new Set(listValue("#source-blocks")),
    all = $("#source-show-all").checked,
    root = $("#original-blocks");
  root.replaceChildren();
  for (const page of currentDoc.payload.normalized.pages)
    for (const block of page.blocks) {
      if (!all && !selected.has(block.block_id)) continue;
      const section = element("section", undefined, "source-option"),
        label = element("label", undefined, "check"),
        box = element("input");
      box.type = "checkbox";
      box.checked = selected.has(block.block_id);
      box.dataset.sourceBlock = block.block_id;
      box.addEventListener("change", () => {
        const ids = new Set(listValue("#source-blocks"));
        box.checked ? ids.add(block.block_id) : ids.delete(block.block_id);
        $("#source-blocks").value = [...ids].join(", ");
      });
      label.append(
        box,
        element(
          "span",
          `PDF 第 ${page.pdf_page_index + 1} 页 · ${block.block_type}`,
        ),
      );
      const jump = element("button", "查看这一页", "secondary");
      jump.type = "button";
      jump.addEventListener("click", () => showPage(page.pdf_page_index + 1));
      section.append(label, jump, element("pre", block.text));
      for (const ref of block.asset_refs) {
        const link = element("a", "查看原始图表");
        link.href = currentDoc.asset_links[ref] || "#";
        link.target = "_blank";
        link.rel = "noopener";
        section.append(link);
      }
      root.append(section);
    }
}
$("#source-show-all").addEventListener("change", renderSourceOptions);

function renderContextOptions() {
  const root = $("#context-picker");
  root.replaceChildren();
  if (!currentDoc) return;
  const current = currentDoc.payload.candidates.find(
    (r) => r.id === selectedCandidate,
  )?.record;
  const choices = new Map(reviewOptions.map((row) => [row.clause_uid, row]));
  for (const item of currentDoc.payload.candidates) {
    const r = item.record;
    if (r.clause_uid)
      choices.set(r.clause_uid, {
        clause_uid: r.clause_uid,
        clause_no: r.clause_no,
        standard_code: r.standard_code,
        text: r.text_verbatim.slice(0, 180),
        status: r.content_review_status,
      });
  }
  const selected = new Set(listValue("#context-uids")),
    query = $("#context-search").value.toLowerCase();
  for (const row of choices.values()) {
    if (row.clause_uid === current?.clause_uid) continue;
    if (
      query &&
      !selected.has(row.clause_uid) &&
      !(row.clause_no + " " + row.text).toLowerCase().includes(query)
    )
      continue;
    const label = element("label", undefined, "check"),
      box = element("input");
    box.type = "checkbox";
    box.checked = selected.has(row.clause_uid);
    box.addEventListener("change", () => {
      const values = new Set(listValue("#context-uids"));
      box.checked ? values.add(row.clause_uid) : values.delete(row.clause_uid);
      $("#context-uids").value = [...values].join(", ");
    });
    label.append(
      box,
      element(
        "span",
        `${row.standard_code} §${row.clause_no} · ${labels[row.status]} — ${row.text.slice(0, 100)}`,
      ),
    );
    root.append(label);
  }
  if (!choices.size)
    root.textContent = "先保存标准身份信息，即可按条款号选择上下文。";
  for (const uid of selected)
    if (!choices.has(uid))
      root.append(
        element(
          "p",
          "有一项历史关联无法在当前候选中找到，请在开发者详情中核对。",
          "notice warning",
        ),
      );
}
$("#context-search").addEventListener("input", renderContextOptions);

function reviewDirty() {
  if (!currentDoc || !selectedCandidate) return false;
  const record = currentDoc.payload.candidates.find(
    (row) => row.id === selectedCandidate,
  )?.record;
  if (!record) return false;
  return (
    candidateDirty() ||
    [...document.querySelectorAll("#metadata-fields [name]")].some(
      (n) =>
        n.value !==
        (currentDoc.payload.metadata?.[n.name] || record[n.name] || ""),
    )
  );
}
window.addEventListener("beforeunload", (event) => {
  if (
    (view === "review" && reviewDirty()) ||
    (view === "setup" && window.setupUI?.isDirty())
  ) {
    event.preventDefault();
    event.returnValue = "";
  }
});
$("#save-next-clause").addEventListener("click", () =>
  run(async () => {
    await candidateAction("edit", {
      changes: {
        text_verbatim: $("#clause-text").value,
        clause_no: $("#clause-no").value,
        clause_path: $("#clause-path")
          .value.split("/")
          .map((x) => x.trim())
          .filter(Boolean),
        context_clause_uids: listValue("#context-uids"),
        review_notes: $("#review-notes").value,
      },
      block_ids: listValue("#source-blocks"),
    });
    const rows = currentDoc.payload.candidates,
      index = rows.findIndex((r) => r.id === selectedCandidate),
      next = rows
        .slice(index + 1)
        .find((r) => r.record.content_review_status !== "approved");
    if (next) {
      $("#candidate-filter").value = "all";
      $("#candidate-search").value = "";
      renderCandidateFilter(next.id);
    } else message("已保存，后面没有待复核候选。保存修改不会自动批准。");
  }, $("#save-next-clause")),
);

function renderReleaseEditor() {
  const blockers = $("#release-blockers");
  blockers.replaceChildren();
  for (const problem of releasePreview.blockers || []) {
    const row = element("div", undefined, "notice warning");
    row.append(
      element(
        "p",
        `${problem.standard_code} §${problem.clause_no}：${problem.message}`,
      ),
    );
    if (problem.document_id) {
      const b = element("button", "打开关联复核位置", "secondary");
      b.type = "button";
      b.addEventListener("click", () =>
        run(async () => {
          $("#candidate-filter").value = "all";
          $("#candidate-search").value = "";
          await openDocument(problem.document_id);
          renderCandidateFilter(problem.candidate_id);
        }, b),
      );
      row.append(b);
    }
    blockers.append(row);
  }
  if (releasePreview.replacement_details?.length)
    $("#release-summary").textContent +=
      "\n替换明细：\n" +
      releasePreview.replacement_details
        .map(
          (r) =>
            `${r.standard_code} ${r.standard_name}：${r.before} → ${r.after} 条`,
        )
        .join("\n");
  if (!caseRows.length)
    caseRows.push({
      case_id: "case_" + crypto.randomUUID().replaceAll("-", ""),
      query: "",
      expected_clause_uids: [],
      answerable: true,
    });
  drawCases();
}
function drawCases() {
  const root = $("#retrieval-case-editor");
  root.replaceChildren();
  for (const [index, row] of caseRows.entries()) {
    const card = element("section", undefined, "case-card"),
      title = element("div", undefined, "section-head"),
      remove = element("button", "删除本题", "secondary");
    remove.type = "button";
    remove.addEventListener("click", () => {
      caseRows = caseRows.filter((r) => r !== row);
      drawCases();
    });
    title.append(element("strong", `问题 ${index + 1}`), remove);
    const label = element("label", "用自己的语言填写检索问题"),
      query = element("textarea");
    query.rows = 2;
    query.maxLength = 250;
    query.value = row.query;
    query.placeholder = "例如：防护装置的连接需要满足哪些要求？";
    query.addEventListener("input", () => {
      row.query = query.value;
      syncCasesJson();
    });
    label.append(query);
    const noneLabel = element("label", undefined, "check"),
      none = element("input");
    none.type = "checkbox";
    none.checked = !row.answerable;
    noneLabel.append(
      none,
      element("span", "这是无答案问题（本次已批准语料不包含答案）"),
    );
    const targets = element("div", undefined, "option-list");
    for (const clause of releasePreview.records) {
      const l = element("label", undefined, "check"),
        box = element("input");
      box.type = "checkbox";
      box.checked = row.expected_clause_uids.includes(clause.clause_uid);
      box.disabled = !row.answerable;
      box.addEventListener("change", () => {
        row.expected_clause_uids = box.checked
          ? [...row.expected_clause_uids, clause.clause_uid]
          : row.expected_clause_uids.filter((u) => u !== clause.clause_uid);
        syncCasesJson();
      });
      l.append(
        box,
        element(
          "span",
          `${clause.standard_code} §${clause.clause_no} — ${clause.text_verbatim.slice(0, 120)}`,
        ),
      );
      targets.append(l);
    }
    none.addEventListener("change", () => {
      row.answerable = !none.checked;
      if (!row.answerable) row.expected_clause_uids = [];
      drawCases();
    });
    card.append(
      title,
      label,
      noneLabel,
      element("p", "勾选预期命中的条款（可多选，必须由复核人确认）：", "hint"),
      targets,
    );
    const allowed = new Set(releasePreview.records.map((r) => r.clause_uid));
    if (row.expected_clause_uids.some((uid) => !allowed.has(uid))) {
      const reset = element("button", "移除不在当前范围的目标", "secondary");
      reset.type = "button";
      reset.addEventListener("click", () => {
        row.expected_clause_uids = row.expected_clause_uids.filter((uid) =>
          allowed.has(uid),
        );
        drawCases();
      });
      card.append(
        element(
          "p",
          "本题包含不在当前批准范围的目标，请重新标注。",
          "notice warning",
        ),
        reset,
      );
    }
    root.append(card);
  }
  syncCasesJson();
}
function syncCasesJson() {
  $("#release-cases").value = JSON.stringify(caseRows, null, 2);
}
function collectCases() {
  if (!caseRows.length || !caseRows.some((r) => r.answerable))
    throw new Error("至少添加一道可回答问题");
  const allowed = new Set(releasePreview.records.map((r) => r.clause_uid));
  for (const [index, row] of caseRows.entries())
    if (
      !row.query.trim() ||
      (row.answerable && !row.expected_clause_uids.length) ||
      row.expected_clause_uids.some((u) => !allowed.has(u))
    )
      throw new Error(
        `问题 ${index + 1} 尚未填写完整或目标已失效，请核对问题和条款选择`,
      );
  return caseRows.map((r) => ({ ...r, query: r.query.trim() }));
}
$("#add-retrieval-case").addEventListener("click", () => {
  caseRows.push({
    case_id: "case_" + crypto.randomUUID().replaceAll("-", ""),
    query: "",
    expected_clause_uids: [],
    answerable: true,
  });
  drawCases();
});

$("#equipment-images").addEventListener("change", () => {
  const files = [...$("#equipment-images").files];
  if (
    files.length > 4 ||
    files.some(
      (f) =>
        f.size > 5 * 1024 * 1024 ||
        !["image/jpeg", "image/png"].includes(f.type),
    )
  ) {
    message("请选择 1～4 张 JPEG/PNG，每张不超过 5 MiB。", true);
    $("#equipment-images").value = "";
    selectedImages = [];
    renderImages();
    return;
  }
  selectedImages = files;
  renderImages();
});
function renderImages() {
  for (const url of imageUrls) URL.revokeObjectURL(url);
  imageUrls = [];
  const root = $("#image-preview");
  root.replaceChildren();
  selectedImages.forEach((file, index) => {
    const card = element("div", undefined, "image-card"),
      img = element("img");
    img.alt = `第 ${index + 1} 张：${file.name}`;
    img.src = URL.createObjectURL(file);
    imageUrls.push(img.src);
    card.append(img, element("p", `${index + 1}. ${file.name}`));
    for (const [text, move] of [
      ["前移", -1],
      ["后移", 1],
      ["移除", 0],
    ]) {
      const b = element("button", text, "secondary");
      b.type = "button";
      b.disabled =
        (move === -1 && index === 0) ||
        (move === 1 && index === selectedImages.length - 1);
      b.addEventListener("click", () => {
        if (!move) selectedImages.splice(index, 1);
        else
          [selectedImages[index], selectedImages[index + move]] = [
            selectedImages[index + move],
            selectedImages[index],
          ];
        renderImages();
      });
      card.append(b);
    }
    root.append(card);
  });
}

async function openTaskDiagnostics(id) {
  $("#report-panel").hidden = true;
  $("#task-diagnostics-panel").hidden = true;
  const data = await api(`/api/jobs/${id}/diagnostics`),
    root = $("#task-diagnostics-content");
  root.replaceChildren();
  root.append(
    element(
      "p",
      `任务 ${id} · ${stages[data.stage] || data.stage} · ${labels[data.status] || data.status}`,
    ),
    element(
      "p",
      `本次读取：${new Date(data.generated_at).toLocaleString()}；日志为有限快照。`,
      "hint",
    ),
  );
  const refreshLog = element("button", "刷新此任务诊断", "secondary");
  refreshLog.type = "button";
  refreshLog.addEventListener("click", () =>
    run(() => openTaskDiagnostics(id), refreshLog),
  );
  root.append(refreshLog);
  if (data.error?.message) {
    root.append(element("p", data.error.message, "notice warning"));
    if (data.error.suggestion) root.append(element("p", data.error.suggestion));
  }
  if (Object.keys(data.references || {}).length)
    root.append(element("pre", JSON.stringify(data.references, null, 2)));
  for (const event of data.events || []) {
    const info = event.error || {},
      line = element("div", undefined, "event-row");
    line.append(
      element(
        "strong",
        `${new Date(event.created_at).toLocaleString()} · ${info.title || stages[event.stage] || event.stage} · ${info.event || labels[event.status] || event.status}`,
      ),
    );
    if (info.message || info.error)
      line.append(element("p", info.message || String(info.error)));
    if (Object.keys(info).length) {
      const d = element("details");
      d.append(
        element("summary", "脱敏详情"),
        element("pre", JSON.stringify(info, null, 2)),
      );
      line.append(d);
    }
    root.append(line);
  }
  if (data.retrieval_evaluation) {
    const d = element("details");
    d.open = true;
    d.append(
      element("summary", "检索自检结果"),
      element("pre", JSON.stringify(data.retrieval_evaluation, null, 2)),
    );
    root.append(d);
  }
  for (const [name, text] of Object.entries(data.logs || {})) {
    const d = element("details");
    d.open = true;
    d.append(
      element("summary", name),
      element(
        "pre",
        typeof text === "string" ? text : JSON.stringify(text, null, 2),
        "log-box",
      ),
    );
    root.append(d);
  }
  const errorDetails = element("details");
  errorDetails.append(
    element("summary", "错误字段与技术详情"),
    element("pre", JSON.stringify(data.error, null, 2)),
  );
  root.append(errorDetails);
  $("#download-task-diagnostics").href = `/api/jobs/${id}/diagnostics.zip`;
  $("#task-diagnostics-panel").hidden = false;
  $("#task-diagnostics-panel").scrollIntoView({ behavior: "smooth" });
}
window.addEventListener("unhandledrejection", (event) => {
  displayError({
    code: "page_error",
    message: "页面操作未完成，请刷新状态后查看任务记录。",
  });
  event.preventDefault();
});
window.addEventListener("error", () =>
  displayError({
    code: "page_error",
    message: "页面脚本发生异常，请保留任务编号并查看开发者控制台。",
  }),
);
$("#source-pdf").addEventListener("error", () =>
  displayError({
    code: "pdf_preview_error",
    message: "原始 PDF 页预览加载失败，请查看服务日志或打开原始 PDF。",
  }),
);
