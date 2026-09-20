"use strict";

// 调用原单文件上传/原任务重试接口；文件内容不进入浏览器持久化存储。
function createPdfUploadQueue(
  transport,
  onChange = () => {},
  limits = () => ({}),
) {
  const rows = [],
    retryingJobs = new Set();
  let running = false,
    sequence = 0,
    order = 0;
  const notify = () => onChange();
  const detail = (error) =>
    error.info || {
      code: "upload_error",
      message: error.message || "操作失败，请查看服务日志",
    };
  function validation(file) {
    if (!/\.pdf$/i.test(file.name))
      return { code: "invalid_pdf", message: "请选择 PDF 文件" };
    if (!file.size) return { code: "invalid_file", message: "不能上传空文件" };
    const max = limits().max_pdf_bytes;
    if (max && file.size > max)
      return {
        code: "file_too_large",
        message: `文件超过每份 ${Math.round(max / 1048576)} MiB 的限制`,
      };
    return null;
  }
  function addFiles(files) {
    for (const file of Array.from(files)) {
      const error = validation(file);
      rows.push({
        id: "upload_" + ++sequence,
        order: ++order,
        name: file.name,
        size: file.size,
        file,
        phase: error ? "upload_failed" : "ready",
        error,
        document_id: "",
        parse_job: null,
        document: null,
        reused: false,
        sync_error: null,
        retry_error: null,
      });
    }
    notify();
  }
  async function start() {
    if (running) return;
    running = true;
    notify();
    try {
      while (true) {
        const row = rows
          .filter((r) => r.phase === "ready")
          .sort((a, b) => a.order - b.order)[0];
        if (!row) break;
        const invalid = validation(row.file);
        if (invalid) {
          row.phase = "upload_failed";
          row.error = invalid;
          notify();
          continue;
        }
        row.phase = "uploading";
        row.error = null;
        notify();
        try {
          const result = await transport.upload(row.file);
          if (typeof result?.document_id !== "string" || !result.document_id)
            throw new Error("上传返回缺少文档标识，请核对任务列表后重试");
          row.document_id = result.document_id;
          row.reused = !!result.reused;
          row.parse_job = result.parse_job || null;
          row.phase = "received";
          row.file = null;
        } catch (error) {
          row.phase = "upload_failed";
          row.error = detail(error);
        }
        notify();
      }
    } finally {
      running = false;
      notify();
    }
  }
  async function retryUpload(id) {
    const row = rows.find((r) => r.id === id);
    if (!row || row.phase !== "upload_failed" || !row.file) return;
    row.phase = "ready";
    row.order = ++order;
    row.error = null;
    notify();
    await start();
  }
  function updateJob(row, job) {
    if (!job) return;
    const oldTime = Date.parse(row.parse_job?.updated_at),
      newTime = Date.parse(job.updated_at);
    if (
      Number.isFinite(oldTime) &&
      Number.isFinite(newTime) &&
      (newTime < oldTime ||
        (newTime === oldTime && job.updated_at < row.parse_job.updated_at))
    )
      return;
    if (row.parse_job?.status !== job.status) row.retry_error = null;
    row.parse_job = job;
  }
  function updateDocuments(documents) {
    const byId = new Map(documents.map((d) => [d.id, d]));
    for (const row of rows) {
      const doc = byId.get(row.document_id);
      if (doc) {
        if (!row.document || doc.revision >= row.document.revision)
          row.document = doc;
        updateJob(row, doc.parse_job);
        row.sync_error = null;
      } else if (row.document_id)
        row.sync_error = {
          message: "当前列表未找到该文档，请刷新并核对资料目录。",
        };
    }
    notify();
  }
  async function retryParse(id) {
    const row = rows.find((r) => r.id === id),
      job = row?.parse_job;
    if (
      !job ||
      !["failed", "interrupted", "needs_attention"].includes(job.status) ||
      retryingJobs.has(job.id)
    )
      return;
    retryingJobs.add(job.id);
    row.retry_error = null;
    notify();
    try {
      const result = await transport.retry(job.id);
      if (result?.id !== job.id)
        throw new Error("重试返回的任务身份不一致，请核对任务诊断");
      for (const item of rows.filter((r) => r.parse_job?.id === job.id))
        updateJob(item, result);
    } catch (error) {
      row.retry_error = detail(error);
    } finally {
      retryingJobs.delete(job.id);
      notify();
    }
  }
  function remove(id) {
    const index = rows.findIndex((r) => r.id === id);
    if (index >= 0 && ["ready", "upload_failed"].includes(rows[index].phase)) {
      rows.splice(index, 1);
      notify();
    }
  }
  function clearCompleted() {
    for (let i = rows.length - 1; i >= 0; i--)
      if (
        rows[i].phase === "received" &&
        rows[i].parse_job?.status === "succeeded"
      )
        rows.splice(i, 1);
    notify();
  }
  function pollFailed(error) {
    for (const row of rows) if (row.document_id) row.sync_error = detail(error);
    notify();
  }
  return {
    rows,
    retryingJobs,
    get running() {
      return running;
    },
    addFiles,
    start,
    retryUpload,
    retryParse,
    updateDocuments,
    pollFailed,
    remove,
    clearCompleted,
    hasLocalFiles: () => rows.some((r) => !!r.file),
  };
}

function bindPdfDropZone(zone, addFiles) {
  const hasFiles = (event) =>
    Array.from(event.dataTransfer?.types || []).includes("Files");
  zone.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    zone.classList.add("dragging");
  });
  zone.addEventListener("dragleave", (event) => {
    if (!event.relatedTarget?.nodeType || !zone.contains(event.relatedTarget))
      zone.classList.remove("dragging");
  });
  zone.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.stopPropagation();
    zone.classList.remove("dragging");
    addFiles(event.dataTransfer.files);
  });
}

if (typeof window !== "undefined")
  window.uploadUI = (() => {
    const cards = new Map();
    let refreshTimer = null;
    const queue = createPdfUploadQueue(
      {
        upload: async (file) => {
          const body = new FormData();
          body.append("file", file);
          const result = await api("/api/documents", { method: "POST", body });
          clearTimeout(refreshTimer);
          refreshTimer = setTimeout(() => run(refreshDocuments), 100);
          return result;
        },
        retry: async (id) => {
          const result = await post(
            `/api/jobs/${encodeURIComponent(id)}/retry`,
            {},
          );
          clearTimeout(refreshTimer);
          refreshTimer = setTimeout(() => run(refreshDocuments), 100);
          return result;
        },
      },
      render,
      () => lastStatus || {},
    );
    function stateText(row) {
      if (row.phase === "ready") return "待上传";
      if (row.phase === "uploading") return "上传中…";
      if (row.phase === "upload_failed") return "上传失败";
      const job = row.parse_job;
      if (!job)
        return row.document?.candidate_count
          ? "已有解析记录，待人工复核"
          : "已接收，解析状态待同步";
      if (job.status === "queued") return "上传已接收 · 等待解析";
      if (job.status === "running")
        return "上传已接收 · " + (stages[job.stage] || "解析处理中");
      if (job.status === "succeeded")
        return row.document?.full_document_covered === false
          ? "解析结束 · 页覆盖需核对，不能批准"
          : "解析完成 · 保留人工复核流程";
      return "解析" + (labels[job.status] || job.status);
    }
    function addError(card, error, heading) {
      if (!error?.message) return;
      card.append(element("p", heading + error.message, "notice warning"));
      if (error.suggestion) card.append(element("p", error.suggestion, "hint"));
      const more = element("details");
      more.append(
        element("summary", "排查详情"),
        element("pre", JSON.stringify(error, null, 2)),
      );
      card.append(more);
    }
    function button(text, action) {
      const b = element("button", text, "secondary");
      b.type = "button";
      b.addEventListener("click", () => run(action));
      return b;
    }
    function render() {
      const root = $("#pdf-upload-queue");
      for (const [id, value] of cards)
        if (!queue.rows.some((r) => r.id === id)) {
          value.node.remove();
          cards.delete(id);
        }
      for (const row of queue.rows) {
        let cached = cards.get(row.id);
        if (!cached) {
          const node = element("section", undefined, "pdf-upload-row");
          node.dataset.uploadId = row.id;
          root.append(node);
          cached = { node, signature: "" };
          cards.set(row.id, cached);
        }
        const signature = JSON.stringify([
          row.phase,
          row.error,
          row.document,
          row.parse_job,
          row.reused,
          row.sync_error,
          row.retry_error,
          queue.retryingJobs.has(row.parse_job?.id),
        ]);
        if (signature === cached.signature) continue;
        cached.signature = signature;
        const card = cached.node;
        card.replaceChildren();
        const header = element("div", undefined, "section-head");
        header.append(
          element("strong", row.name),
          element("span", stateText(row), "tag"),
        );
        card.append(header);
        card.append(
          element(
            "p",
            `${(row.size / 1048576).toFixed(2)} MiB${row.reused ? " · 重复内容：已复用原文档、解析任务与人工复核记录" : ""}`,
            "hint",
          ),
        );
        if (row.document)
          card.append(
            element(
              "p",
              `${row.document.page_count} 页 · ${row.document.approved_count} / ${row.document.candidate_count} 条已批准${row.document.filename !== row.name ? " · 原记录：" + row.document.filename : ""}`,
              "hint",
            ),
          );
        if (row.phase === "uploading") {
          const progress = element("progress");
          progress.setAttribute("aria-label", row.name + " 上传中");
          card.append(progress);
        }
        addError(card, row.error, "");
        addError(card, row.parse_job?.error, "解析原因：");
        if (
          ["failed", "interrupted", "needs_attention"].includes(
            row.parse_job?.status,
          ) &&
          !row.parse_job.error?.message
        )
          card.append(
            element(
              "p",
              "解析未正常完成，未记录具体异常；请查看任务诊断后重试此文件。",
              "notice warning",
            ),
          );
        addError(card, row.retry_error, "重试未完成：");
        addError(card, row.sync_error, "状态暂未更新（保留上次结果）：");
        const actions = element("div", undefined, "actions");
        if (row.phase === "upload_failed")
          actions.append(
            button("重试此文件上传", () => queue.retryUpload(row.id)),
          );
        if (["ready", "upload_failed"].includes(row.phase))
          actions.append(button("移出本批次", () => queue.remove(row.id)));
        if (
          ["failed", "interrupted", "needs_attention"].includes(
            row.parse_job?.status,
          )
        ) {
          const retry = button("重试此文件解析", () =>
            queue.retryParse(row.id),
          );
          retry.disabled = queue.retryingJobs.has(row.parse_job.id);
          actions.append(retry);
        }
        if (row.parse_job?.id)
          actions.append(
            button("查看任务诊断", async () => {
              show("jobs");
              await openTaskDiagnostics(row.parse_job.id);
            }),
          );
        if (row.document?.candidate_count)
          actions.append(
            button("对照复核", () => openDocument(row.document_id)),
          );
        card.append(actions);
      }
      const ready = queue.rows.filter((r) => r.phase === "ready").length,
        uploading = queue.rows.filter((r) => r.phase === "uploading").length,
        failed = queue.rows.filter(
          (r) =>
            r.phase === "upload_failed" ||
            ["failed", "interrupted", "needs_attention"].includes(
              r.parse_job?.status,
            ),
        ).length,
        received = queue.rows.filter((r) => r.phase === "received").length;
      $("#pdf-batch-summary").textContent = queue.rows.length
        ? `本批次 ${queue.rows.length} 个文件 · 待上传 ${ready} · 上传中 ${uploading} · 已接收 ${received} · 失败/待处理 ${failed}。状态随文档列表更新。`
        : "尚未选择文件。";
      $("#start-pdf-uploads").disabled = queue.running || !ready;
      $("#start-pdf-uploads").textContent = queue.running
        ? "正在逐份上传…"
        : "上传所选 PDF";
      $("#clear-pdf-uploads").disabled = !queue.rows.some(
        (r) => r.phase === "received" && r.parse_job?.status === "succeeded",
      );
    }
    $("#pdf-file").addEventListener("change", () => {
      queue.addFiles($("#pdf-file").files);
      $("#pdf-file").value = "";
    });
    $("#upload-form").addEventListener("submit", (event) => {
      event.preventDefault();
      run(() => queue.start());
    });
    $("#clear-pdf-uploads").addEventListener("click", () =>
      queue.clearCompleted(),
    );
    bindPdfDropZone($("#pdf-dropzone"), (files) => queue.addFiles(files));
    for (const name of ["dragover", "drop"])
      window.addEventListener(name, (event) => {
        if (
          view === "library" &&
          Array.from(event.dataTransfer?.types || []).includes("Files")
        ) {
          event.preventDefault();
          if (name === "drop" && !$("#pdf-dropzone").contains(event.target))
            message("请把文件拖入 PDF 批量上传区。", true);
        }
      });
    window.addEventListener("beforeunload", (event) => {
      if (queue.hasLocalFiles()) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
    return {
      updateDocuments: queue.updateDocuments,
      pollFailed: queue.pollFailed,
    };
  })();
