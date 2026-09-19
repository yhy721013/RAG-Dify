"use strict";
const $ = (selector) => document.querySelector(selector);
let csrf = "",
  currentDoc = null,
  releasePreview = null,
  selectedCandidate = "",
  view = "library";
let submissionId = crypto.randomUUID();
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
}
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET")
    headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error?.message || "请求失败，请检查输入或后台状态");
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
    message(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
function show(name) {
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
  }[name];
}
async function status() {
  const data = await api("/api/status");
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
      ? "待配置：" +
        missing.join("、") +
        "。请参照 docs/portal-runbook.md 填写 .env.portal。"
      : "服务配置已齐备。") +
    (alive ? " 后台任务进程在线。" : " 后台任务进程未就绪，请运行启动脚本。");
  $("#readiness").classList.toggle("warning", missing.length > 0 || !alive);
  $("#upload-limit").textContent =
    `PDF · 最高 ${Math.round(data.max_pdf_bytes / 1048576)} MiB / ${data.max_pdf_pages} 页 · 每次一份`;
  $("#assessment-version").textContent = data.current_snapshot
    ? "本次将使用已发布知识版本：" + data.current_snapshot
    : "请先完成标准复核并发布知识版本。";
}
async function refreshDocuments() {
  const rows = await api("/api/documents"),
    root = $("#documents");
  const signature = JSON.stringify(rows);
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
        { parse: "标准解析", publish: "知识版本发布", assessment: "设备评估" }[
          row.kind
        ] +
          " · " +
          (stages[row.stage] || row.stage),
      ),
      element(
        "div",
        row.id + " · " + new Date(row.created_at).toLocaleString(),
        "meta",
      ),
    );
    if (row.result?.run_id)
      info.append(element("div", "Dify 运行：" + row.result.run_id, "meta"));
    if (row.error?.message)
      info.append(element("div", row.error.message, "meta"));
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
    if (["failed", "interrupted", "needs_attention"].includes(row.status)) {
      const b = element("button", "恢复 / 对账", "secondary");
      b.addEventListener("click", () =>
        run(async () => {
          await post(`/api/jobs/${row.id}/retry`, {});
          await refreshJobs();
        }, b),
      );
      line.append(b);
    }
    root.append(line);
  }
}
async function openReport(id) {
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
}
async function openDocument(id) {
  const doc = await api(`/api/documents/${id}`);
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
  const root = $("#original-blocks");
  root.replaceChildren();
  for (const page of currentDoc.payload.normalized.pages) {
    for (const block of page.blocks) {
      const section = element("div");
      section.append(
        element(
          "strong",
          `PDF 第 ${page.pdf_page_index + 1} 页 · ${block.block_id} · ${block.block_type}`,
        ),
        element("pre", block.text),
      );
      for (const ref of block.asset_refs) {
        const link = element("a", "查看图表：" + ref);
        link.href = currentDoc.asset_links[ref] || "#";
        link.target = "_blank";
        link.rel = "noopener";
        section.append(link);
      }
      root.append(section);
    }
  }
  const first = record.source_spans[0];
  if (first) showPage(first.pdf_page_index + 1);
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
    $("#publish-release").disabled = releasePreview.unchanged;
    if (releasePreview.unchanged)
      $("#release-summary").textContent +=
        "\n已批准内容没有变化，无需重复发布。";
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
      cases: JSON.parse($("#release-cases").value),
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
    for (const file of $("#equipment-images").files)
      body.append("images", file);
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
        `${index + 1}. ${states[finding.status] || finding.status}`,
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
