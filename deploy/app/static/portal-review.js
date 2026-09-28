"use strict";
window.reviewUI = (() => {
  let selected = new Set(),
    page = 0,
    lastDocument = "";
  const size = 8;
  const diffLabels = {
    new: "首次复核",
    added: "新增条款",
    modified: "内容/条件变化",
    dependency_affected: "受依赖变化影响",
    unchanged: "与基准未变",
    ambiguous: "基准编号不唯一",
  };
  const $row = (id) =>
    currentDoc?.assistance?.rows.find((r) => r.candidate_id === id);
  const $item = (id) => currentDoc?.payload.candidates.find((r) => r.id === id);
  function reviewSelection(id) {
    if (reviewDirty())
      throw new Error("请先保存当前条款编辑，再切换集中复核位置");
    $("#candidate-filter").value = "all";
    $("#candidate-search").value = "";
    renderCandidateFilter(id);
    $("#candidate-info").scrollIntoView({ behavior: "smooth" });
  }
  function render() {
    const data = currentDoc?.assistance;
    $("#review-assistance").hidden = !data;
    if (!data) return;
    $("#review-assistance").open = !!Object.keys(
      currentDoc.payload.metadata || {},
    ).length;
    if (lastDocument !== currentDoc.id) {
      $("#batch-filter").value = data.baseline ? "changed" : "pending";
      $("#batch-search").value = "";
    }
    lastDocument = currentDoc.id;
    selected.clear();
    page = 0;
    for (const checkbox of document.querySelectorAll(
      "#batch-acknowledgements input",
    ))
      checkbox.checked = false;
    $("#review-assistance-summary").textContent =
      `无规则疑点 ${data.counts.normal || 0} 条 · 异常待处理 ${data.counts.exception || 0} 条 · 已复核 ${data.counts.reviewed || 0} 条。${data.limitation}`;
    const checks = $("#document-checks");
    checks.replaceChildren();
    for (const check of data.document_checks)
      checks.append(
        element(
          "p",
          check.message +
            (check.pages?.length ? `：PDF第 ${check.pages.join("、")} 页` : ""),
          "notice warning",
        ),
      );
    if (Object.keys(data.metadata_changes || {}).length) {
      const changed = element("details");
      changed.append(
        element(
          "summary",
          "标准信息变更（核验日期/来源变化单列，不算原文变化）",
        ),
      );
      for (const [key, value] of Object.entries(data.metadata_changes))
        changed.append(
          element(
            "p",
            `${metadataNames[key] || key}：${value.before} → ${value.after}`,
          ),
        );
      checks.append(changed);
    }
    const baseline = $("#review-baseline");
    baseline.replaceChildren();
    const auto = element(
      "option",
      data.baseline
        ? `当前基准：${data.baseline.filename} · 复核版本 ${data.baseline.revision}`
        : "暂无同标准的批准基准",
    );
    auto.value = "";
    baseline.append(auto);
    for (const row of data.baseline_choices) {
      const option = element("option", row.filename);
      option.value = row.id;
      baseline.append(option);
    }
    $("#metadata-suggestion-note").textContent =
      data.metadata_draft.note +
      " 来源：" +
      Object.entries(data.metadata_draft.provenance)
        .map(
          ([k, v]) =>
            `${metadataNames[k]}（${v.rule}，PDF ${v.page || v.pages?.join("、")} 页）`,
        )
        .join("；");
    const removed = $("#removed-clauses");
    removed.replaceChildren();
    for (const row of data.removed)
      removed.append(
        element("h4", "§" + row.clause_no),
        element("pre", row.text),
      );
    $("#removed-clause-panel").hidden = !data.removed.length;
    draw();
    renderCandidate();
  }
  function filtered() {
    const filter = $("#batch-filter").value,
      query = $("#batch-search").value.trim().toLowerCase();
    return (currentDoc?.assistance?.rows || []).filter((row) => {
      const record = $item(row.candidate_id).record;
      return (
        (!query ||
          (row.clause_no + " " + record.text_verbatim)
            .toLowerCase()
            .includes(query)) &&
        (filter === "all" ||
          (filter === "pending" &&
            record.content_review_status !== "approved") ||
          filter === row.group ||
          (filter === "changed" &&
            ["modified", "added", "dependency_affected", "ambiguous"].includes(
              row.diff.status,
            )) ||
          (filter === "unchanged" && row.diff.status === "unchanged"))
      );
    });
  }
  function draw() {
    const rows = filtered(),
      root = $("#batch-cards");
    root.replaceChildren();
    page = Math.max(0, Math.min(page, Math.ceil(rows.length / size) - 1));
    for (const row of rows.slice(page * size, (page + 1) * size)) {
      const record = $item(row.candidate_id).record,
        card = element("section", undefined, "review-batch-card"),
        head = element("div", undefined, "section-head");
      const label = element("label", undefined, "check"),
        box = element("input");
      box.type = "checkbox";
      box.value = row.candidate_id;
      box.checked = selected.has(row.candidate_id);
      box.disabled = row.group !== "normal";
      box.addEventListener("change", () => {
        box.checked
          ? selected.add(row.candidate_id)
          : selected.delete(row.candidate_id);
        counts(rows);
      });
      label.append(
        box,
        element(
          "strong",
          `§${row.clause_no} · ${diffLabels[row.diff.status]} · ${labels[record.content_review_status]}`,
        ),
      );
      const open = element(
        "button",
        row.group === "exception" ? "逐项处理此异常" : "打开单条复核",
        "secondary",
      );
      open.type = "button";
      open.addEventListener("click", () =>
        run(() => reviewSelection(row.candidate_id), open),
      );
      head.append(label, open);
      card.append(head);
      for (const n of row.pages) {
        const link = element("a", `查看原始PDF第 ${n} 页`);
        link.href = `/api/documents/${currentDoc.id}/pages/${n}`;
        link.target = "_blank";
        link.rel = "noopener";
        card.append(link, document.createTextNode("　"));
      }
      for (const issue of row.issues)
        card.append(
          element(
            "p",
            issue.message +
              (issue.samples ? "：" + issue.samples.join("、") : ""),
            "notice warning",
          ),
        );
      const grid = element("div", undefined, "batch-comparison"),
        original = element("div"),
        candidate = element("div");
      original.append(
        element(
          "h4",
          row.diff.previous_text
            ? row.diff.previous_approved
              ? "基准原文（该条曾批准）"
              : "历史原文（该条未批准）"
            : "解析来源块（仍须对照PDF）",
        ),
      );
      const sources = new Map(
        currentDoc.payload.normalized.pages.flatMap((p) =>
          p.blocks.map((b) => [b.block_id, b.text]),
        ),
      );
      original.append(
        element(
          "pre",
          row.diff.previous_text ||
            record.source_spans
              .flatMap((s) => s.block_ids)
              .map((id) => sources.get(id) || "来源缺失")
              .join("\n"),
        ),
      );
      candidate.append(
        element("h4", "当前待核对原文"),
        element("pre", record.text_verbatim),
      );
      if (row.diff.text_diff?.length) {
        const delta = element("details");
        delta.open = true;
        delta.append(
          element("summary", "变更行（- 基准，+ 当前；完整内容见两侧）"),
          element("pre", row.diff.text_diff.join("\n")),
        );
        card.append(delta);
      }
      grid.append(original, candidate);
      card.append(grid);
      if (row.number_unit_samples.length)
        card.append(
          element(
            "p",
            "数字/单位核对：" + row.number_unit_samples.join("、"),
            "hint",
          ),
        );
      card.append(
        element(
          "p",
          "上下文建议：" +
            (row.suggested_context
              .map((v) => `§${v.clause_no}（${v.reason}）`)
              .join("；") || "无规则建议，请人工确认是否需要上下文"),
          "hint",
        ),
      );
      if (row.context_needs_confirmation)
        card.append(
          element(
            "p",
            "尚未核对上下文建议：可采纳所选建议，或在单条复核中自行调整并保存。",
            "notice warning",
          ),
        );
      root.append(card);
    }
    if (!rows.length)
      root.append(
        element("p", "当前筛选没有条款；可切换筛选查看未变或已复核内容。"),
      );
    $("#batch-previous").disabled = page === 0;
    $("#batch-next").disabled = (page + 1) * size >= rows.length;
    counts(rows);
  }
  function counts(rows = filtered()) {
    $("#batch-count").textContent =
      `共 ${rows.length} 条，显示 ${rows.length ? page * size + 1 : 0}～${Math.min(rows.length, (page + 1) * size)}；已选 ${selected.size} 条（最多100条）。`;
    $("#batch-approve").disabled = !selected.size;
    $("#batch-context").disabled = !selected.size;
  }
  function renderCandidate() {
    const root = $("#candidate-assistance");
    root.replaceChildren();
    const row = $row(selectedCandidate);
    if (!row) return;
    if (row.structure_proposal) {
      const plan = row.structure_proposal,
        panel = element("details");
      panel.append(
        element("summary", `识别到 ${plan.parts.length} 段结构建议`),
        element("p", plan.reason || plan.note),
      );
      for (const part of plan.parts) {
        const detail = element("details");
        detail.append(
          element("summary", `建议层级 ${part.clause_path.join(" → ")}`),
          element("pre", part.text_verbatim),
        );
        panel.append(detail);
      }
      const apply = element("button", "按建议整理为待复核条款", "secondary");
      apply.type = "button";
      apply.disabled = !plan.eligible || row.structure_blocked;
      apply.addEventListener("click", () =>
        run(async () => {
          if (
            !confirm(
              "将按已展示的标题和原始来源整理此待复核段落，并撤销受影响依赖的批准；全部新分段仍需人工复核。继续？",
            )
          )
            return;
          await candidateAction("organize", {
            review_hash: currentDoc.assistance.review_hash,
          });
        }, apply),
      );
      panel.append(apply);
      root.append(panel);
    }
    root.append(
      element(
        "p",
        diffLabels[row.diff.status] +
          " · 自动识别层级：" +
          row.clause_path.join(" → "),
        "hint",
      ),
    );
    for (const issue of row.issues)
      root.append(
        element(
          "p",
          issue.message +
            (issue.samples ? "：" + issue.samples.join("、") : ""),
          "notice warning",
        ),
      );
    if (row.number_unit_samples.length)
      root.append(
        element(
          "p",
          "数字/单位核对：" + row.number_unit_samples.join("、"),
          "hint",
        ),
      );
    if (row.suggested_context.length) {
      const d = element("details");
      d.append(element("summary", "建议上下文关联（人工决定是否采纳）"));
      for (const c of row.suggested_context)
        d.append(element("p", `§${c.clause_no}：${c.reason}`));
      const apply = element("button", "将这些建议加入当前选择", "secondary");
      apply.type = "button";
      apply.addEventListener("click", () => {
        if (row.suggested_context.some((c) => !c.clause_uid)) {
          message("先对照并保存标准身份信息，生成条款身份后再采纳建议。", true);
          return;
        }
        $("#context-uids").value = [
          ...new Set([
            ...listValue("#context-uids"),
            ...row.suggested_context.map((c) => c.clause_uid),
          ]),
        ].join(", ");
        renderContextOptions();
        message("建议已加入当前选择，尚未保存或批准。请核对后保存。");
      });
      d.append(apply);
      root.append(d);
    }
    if (row.diff.previous_text && row.diff.status !== "unchanged") {
      const d = element("details");
      d.append(
        element("summary", "对照变更前原文"),
        element("pre", row.diff.previous_text),
      );
      root.append(d);
    }
  }
  for (const id of ["batch-filter", "batch-search"])
    $("#" + id).addEventListener(
      id === "batch-filter" ? "change" : "input",
      () => {
        page = 0;
        selected.clear();
        draw();
      },
    );
  $("#batch-select").addEventListener("click", () => {
    for (const row of filtered().slice(page * size, (page + 1) * size))
      if (row.group === "normal" && selected.size < 100)
        selected.add(row.candidate_id);
    draw();
  });
  $("#batch-clear").addEventListener("click", () => {
    selected.clear();
    draw();
  });
  $("#batch-previous").addEventListener("click", () => {
    page--;
    draw();
  });
  $("#batch-next").addEventListener("click", () => {
    page++;
    draw();
  });
  $("#review-baseline").addEventListener("change", () =>
    run(async () => {
      if (reviewDirty()) throw new Error("请先保存当前编辑再切换基准");
      await openDocument(currentDoc.id, $("#review-baseline").value);
    }),
  );
  async function submit(action) {
    ensureSavedReview();
    const actor = $("#batch-actor").value.trim();
    if (!actor) throw new Error("请填写实际批量复核人");
    const data = currentDoc.assistance;
    const result = await post(
      `/api/documents/${currentDoc.id}/review/${action}`,
      {
        revision: currentDoc.revision,
        review_hash: data.review_hash,
        baseline_id:
          data.baseline?.id !== currentDoc.id ? data.baseline?.id || "" : "",
        actor,
        candidate_ids: [...selected],
        acknowledgements: [
          ...document.querySelectorAll("#batch-acknowledgements input:checked"),
        ].map((b) => b.value),
      },
    );
    fillDocument(result, selectedCandidate);
    message(
      action === "approve_batch"
        ? "所选普通条款已记录人工批准；发布前仍会核验完整依赖。"
        : "建议关联已保存为待复核内容，请对照后确认批准。",
    );
  }
  $("#batch-context").addEventListener("click", () =>
    run(() => submit("apply_context"), $("#batch-context")).finally(() =>
      counts(),
    ),
  );
  $("#batch-approve").addEventListener("click", () =>
    run(() => submit("approve_batch"), $("#batch-approve")).finally(() =>
      counts(),
    ),
  );
  return { render, renderCandidate };
})();
