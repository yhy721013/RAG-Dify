"use strict";
window.setupUI = (() => {
  let state = null,
    step = "environment",
    tunnel = null,
    diagnosticJob = "",
    pollTimer = null,
    configurationBusy = false;
  const groups = ["environment", "knowledge", "https", "workflow", "checks"];
  const statuses = {
    pass: "通过",
    fail: "未通过",
    warn: "提醒",
    pending: "待实际验证",
  };

  function syncControls() {
    const busy =
      configurationBusy ||
      ["queued", "restarting"].includes(state?.apply?.status);
    $("#apply-setup").disabled = busy || !state?.draft;
    $('#setup-form button[type="submit"]').disabled = busy;
    $("#reload-setup").disabled = busy;
  }

  function selectStep(value) {
    step = groups.includes(value) ? value : "environment";
    for (const node of document.querySelectorAll("[data-setup-group]"))
      node.hidden = node.dataset.setupGroup !== step;
    for (const button of document.querySelectorAll("[data-setup-step]")) {
      button.classList.toggle("active", button.dataset.setupStep === step);
      button.setAttribute(
        "aria-selected",
        String(button.dataset.setupStep === step),
      );
    }
    $("#setup-form").hidden = step === "checks";
  }

  async function load() {
    const current = await api("/api/setup");
    state = current;
    for (const group of groups.filter((g) => g !== "checks"))
      $("#setup-" + group + "-fields").replaceChildren();
    for (const field of state.fields) {
      const label = element("label", field.label),
        input = element("input");
      input.name = field.name;
      input.dataset.configField = field.name;
      input.type = field.type;
      input.dataset.secret = String(field.type === "password");
      input.value = field.value;
      input.autocomplete = field.type === "password" ? "new-password" : "off";
      if (field.type === "password")
        input.placeholder = field.configured
          ? "已配置；留空保留原值"
          : "尚未配置";
      input.disabled = field.environment_override;
      label.append(input);
      if (field.environment_override)
        label.append(
          element(
            "span",
            "由环境变量提供，页面不能覆盖；修改启动环境后重启。",
            "hint",
          ),
        );
      if (field.name === "dify_base_url")
        label.append(
          element(
            "span",
            "Cloud 通常使用 https://api.dify.ai/v1，不能填写控制台页面地址。",
            "hint",
          ),
        );
      if (field.name === "workflow_api_key")
        label.append(
          element(
            "span",
            "应用密钥通常以 app- 开头；实际鉴权结果才是依据。",
            "hint",
          ),
        );
      $("#setup-" + field.group + "-fields").append(label);
    }
    const applied = state.apply?.status;
    $("#setup-state").textContent =
      applied === "queued" || applied === "restarting"
        ? "正在应用配置，等待后台服务就绪…"
        : state.draft
          ? "有已保存草稿。变更项：" +
            (state.draft.changed_fields
              .map(
                (key) => state.fields.find((f) => f.name === key)?.label || key,
              )
              .join("、") || "内容无变化")
          : "正在显示已应用配置；未填写不等于实际鉴权通过。";
    if (applied === "failed")
      $("#setup-state").textContent =
        (state.apply.configuration_restored
          ? "上次应用失败，原配置已恢复。"
          : "配置应用失败且恢复未完成，请查看本机服务日志。") +
        (state.apply.error?.message || "请查看本机服务日志");
    $("#setup-data-root").textContent =
      "资料目录：" + state.data_root + "（本向导不切换资料目录）";
    syncControls();
    $("#diagnose-draft").disabled = !state.draft;
    $("#download-draft-workflow").hidden = !state.draft;
    if (state.draft)
      $("#download-draft-workflow").href =
        "/api/setup/workflow.yml?source=draft&draft_id=" +
        encodeURIComponent(state.draft.id);
    const appId = state.fields.find((f) => f.name === "workflow_app_id")?.value;
    $("#open-workflow-console").href = /^[a-f0-9-]{36}$/i.test(appId || "")
      ? `https://cloud.dify.ai/app/${appId}/workflow`
      : "https://cloud.dify.ai/apps";
    for (const box of document.querySelectorAll("#setup-confirmations input"))
      box.checked = (state.manual_checks?.checks || []).includes(box.value);
    selectStep(step);
    await loadTunnel();
    const result = (await api("/api/diagnostics")).result;
    if (result) renderDiagnostics(result);
  }

  async function loadTunnel() {
    tunnel = await api("/api/setup/tunnel");
    $("#cloudflared-download").href = tunnel.download_url;
    $("#tunnel-state").textContent = tunnel.managed
      ? `本实例状态：${{ connected: "已连接", stopped: "已停止", starting: "连接中", failed: "连接失败" }[tunnel.status] || tunnel.status}。${tunnel.public_url || ""}`
      : tunnel.configured_url
        ? "当前使用已有 HTTPS 地址。本页面尚未创建托管隧道，不会接管已有进程。"
        : "尚未启动本实例隧道，也未配置自有 HTTPS。";
    if (tunnel.status === "stopped" && tunnel.public_url)
      $("#tunnel-state").textContent += " 该地址已过期，请重新启动隧道。";
    else if (tunnel.public_url && tunnel.public_url !== tunnel.configured_url)
      $("#tunnel-state").textContent +=
        " 新地址与当前配置不同：填入、应用后还需同步 Dify。";
    $("#tunnel-start").disabled = !tunnel.tool_exists;
    $("#tunnel-stop").disabled = !tunnel.managed || tunnel.status === "stopped";
    $("#tunnel-use-url").disabled =
      !tunnel.public_url || tunnel.status !== "connected";
  }

  function renderDiagnostics(result) {
    const root = $("#diagnostic-results");
    root.replaceChildren();
    root.append(
      element(
        "p",
        `检查时间：${new Date(result.checked_at).toLocaleString()}${result.stale ? "；配置已变化，本结果过期，请重新检查。" : ""}`,
        result.stale ? "notice warning" : "hint",
      ),
    );
    for (const row of result.checks || []) {
      const card = element(
          "section",
          undefined,
          "diagnostic-row " + row.status,
        ),
        head = element("div", undefined, "section-head");
      head.append(
        element("strong", row.title),
        element("span", statuses[row.status] || row.status, "tag"),
      );
      card.append(head, element("p", row.message));
      if (row.suggestion)
        card.append(element("p", "处理建议：" + row.suggestion, "hint"));
      if (Object.keys(row.details || {}).length) {
        const details = element("details");
        details.append(
          element("summary", "期望、实际值与技术详情"),
          element("pre", JSON.stringify(row.details, null, 2)),
        );
        card.append(details);
      }
      root.append(card);
    }
  }

  async function pollJob(id, after) {
    if (pollTimer) clearTimeout(pollTimer);
    diagnosticJob = id;
    const tick = async () => {
      try {
        const job = await api("/api/jobs/" + id);
        if (["failed", "interrupted", "needs_attention"].includes(job.status)) {
          $("#diagnostic-progress").textContent =
            "任务未完成，可在任务页展开原因。";
          displayError(
            job.error || { message: "任务已中断", code: "interrupted" },
          );
          return;
        }
        if (job.kind === "diagnostics") {
          const partial = (job.events || [])
            .filter((e) => e.stage === "diagnostic_check")
            .map((e) => e.error);
          if (partial.length)
            renderDiagnostics({ checks: partial, checked_at: job.updated_at });
          $("#diagnostic-progress").textContent =
            `正在检查，已取得 ${partial.length} 项结果…`;
        }
        if (job.status === "succeeded") {
          if (job.kind === "diagnostics") {
            renderDiagnostics(job.result);
            $("#diagnostic-progress").textContent = job.result
              .all_connections_passed
              ? job.result.checks.some(
                  (r) => r.id === "workflow.end_to_end" && r.status === "pass",
                )
                ? "本机连接检查完成，且此配置已有真实报告回读记录。"
                : "本机连接检查完成。模型及 Dify 实际回调仍待真实评估验证。"
              : "诊断完成，存在需要处理的项目。";
          }
          if (after) await after(job);
          await refresh();
          return;
        }
        pollTimer = setTimeout(tick, 1500);
      } catch (error) {
        displayError(error);
        pollTimer = setTimeout(tick, 4000);
      }
    };
    await tick();
  }

  for (const button of document.querySelectorAll("[data-setup-step]"))
    button.addEventListener("click", () =>
      selectStep(button.dataset.setupStep),
    );
  $("#setup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run(async () => {
      configurationBusy = true;
      syncControls();
      const values = {};
      for (const input of document.querySelectorAll("[data-config-field]")) {
        if (!input.disabled) values[input.dataset.configField] = input.value;
      }
      try {
        await post("/api/setup/draft", {
          values,
          file_revision: state.file_revision,
        });
        await load();
        message("草稿已保存。原配置仍在使用；空闲时应用并复检。");
      } finally {
        for (const input of document.querySelectorAll(
          '[data-config-field][data-secret="true"]',
        ))
          input.value = "";
        configurationBusy = false;
        syncControls();
      }
    }, event.submitter);
  });
  $("#reload-setup").addEventListener("click", () =>
    run(load, $("#reload-setup")),
  );
  $("#apply-setup").addEventListener("click", () =>
    run(async () => {
      if (!state?.draft) throw new Error("请先保存配置草稿");
      if (isDirty()) throw new Error("页面仍有未保存配置，请先保存草稿");
      configurationBusy = true;
      syncControls();
      try {
        await post("/api/setup/apply", { id: state.draft.id });
        message("配置应用中，页面将自动确认服务恢复。");
        await new Promise((resolve) => {
          const poll = async () => {
            try {
              const next = await api("/api/setup");
              if (["queued", "restarting"].includes(next.apply.status)) {
                setTimeout(poll, 1500);
                return;
              }
              await load();
              await status();
              if (next.apply.status === "failed")
                displayError(next.apply.error);
              else
                message(
                  "配置已应用。请运行已应用配置诊断，并核对 Dify 中相应绑定。",
                );
              resolve();
            } catch (error) {
              displayError(error);
              setTimeout(poll, 3000);
            }
          };
          setTimeout(poll, 1000);
        });
      } finally {
        configurationBusy = false;
        syncControls();
      }
    }),
  );
  for (const source of ["active", "draft"])
    $("#diagnose-" + source).addEventListener("click", () =>
      run(
        async () => {
          const job = await post("/api/diagnostics", {
            source,
            draft_id: source === "draft" ? state?.draft?.id || "" : "",
          });
          selectStep("checks");
          await pollJob(job.id);
        },
        $("#diagnose-" + source),
      ),
    );
  $("#save-confirmations").addEventListener("click", () =>
    run(async () => {
      await post("/api/setup/confirmations", {
        checks: [
          ...document.querySelectorAll("#setup-confirmations input:checked"),
        ].map((n) => n.value),
      });
      message("已记录人工确认；这些项目不会显示为 API 自动验证。");
    }, $("#save-confirmations")),
  );
  $("#generate-evidence-token").addEventListener("click", () => {
    const input = document.querySelector(
      '[data-config-field="evidence_api_token"]',
    );
    if (input.disabled) {
      message("此密钥由环境变量管理，不能从页面替换。", true);
      return;
    }
    if (
      !confirm(
        "生成新密钥后，应用时将替换旧值。请保存前复制并妥善暂存；应用后同步 Dify Secret 并重新发布。",
      )
    )
      return;
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    input.value = [...bytes]
      .map((n) => n.toString(16).padStart(2, "0"))
      .join("");
    input.type = "text";
    input.focus();
    input.select();
    message(
      "新密钥仅此输入框可见。先复制并妥善暂存，再保存草稿；提交后清空。应用后同步到 Dify Secret。",
    );
  });
  for (const action of ["start", "stop", "check"])
    $("#tunnel-" + action).addEventListener("click", () =>
      run(
        async () => {
          const job = await post("/api/setup/tunnel/" + action, {});
          message("隧道操作已提交，可在任务页查看详情。");
          await pollJob(job.id, loadTunnel);
        },
        $("#tunnel-" + action),
      ),
    );
  $("#tunnel-use-url").addEventListener("click", () => {
    if (tunnel.public_url && tunnel.status === "connected") {
      document.querySelector(
        '[data-config-field="evidence_public_url"]',
      ).value = tunnel.public_url;
      message("新地址已填入，尚未保存。应用后须同步 Dify 环境变量并发布。");
    }
  });
  $("#initialize-dataset").addEventListener("click", () =>
    run(async () => {
      const job = await post("/api/setup/initialize-dataset", {});
      message("空库初始化已排队，请在任务页查看结果。");
      await pollJob(job.id);
    }, $("#initialize-dataset")),
  );
  $("#show-service-logs").addEventListener("click", () =>
    run(async () => {
      const result = await api("/api/setup/service-logs");
      $("#service-logs").textContent =
        Object.entries(result.logs)
          .map(([name, text]) => name + "\n" + text)
          .join("\n\n") || "尚无登记的日志。请从项目启动脚本启动服务。";
      $("#service-logs").hidden = false;
    }, $("#show-service-logs")),
  );
  $("#go-first-upload").addEventListener("click", () => show("library"));
  function isDirty() {
    if (!state) return false;
    return [...document.querySelectorAll("[data-config-field]")].some(
      (input) => {
        if (input.disabled) return false;
        const field = state.fields.find(
          (f) => f.name === input.dataset.configField,
        );
        return field.type === "password"
          ? !!input.value
          : input.value !== String(field.value);
      },
    );
  }
  return { load, selectStep, renderDiagnostics, isDirty };
})();
