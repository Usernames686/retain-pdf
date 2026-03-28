const DEVELOPER_PASSWORD = "Gk265157!";
const API_PREFIX = "/api/v1";
const runtimeConfig = window.__FRONT_RUNTIME_CONFIG__ || {};
const DEFAULT_X_API_KEY = runtimeConfig.xApiKey || "blpp-vnlkasgusiodahgtj";

const state = {
  timer: null,
  currentJobId: "",
  developerUnlocked: false,
  uploadId: "",
  uploadedFileName: "",
  uploadedPageCount: 0,
  uploadedBytes: 0,
};

const $ = (id) => document.getElementById(id);

const artifactsOrder = [
  "job_root",
  "source_pdf",
  "layout_json",
  "translations_dir",
  "output_pdf",
  "summary",
];

const BUILTIN_RULE_PROFILES = [
  { name: "general_sci", label: "general_sci" },
  { name: "software_manual", label: "software_manual" },
  { name: "computational_chemistry", label: "computational_chemistry" },
];

const PROVIDER_PRESETS = {
  deepseek: {
    model: "deepseek-chat",
    base_url: "https://api.deepseek.com/v1",
    workers: "50",
  },
  local_q35: {
    model: "Q3.5-turbo",
    base_url: "http://1.94.67.196:10001/v1",
    workers: "4",
  },
};

const DEFAULT_FILE_LABEL = "点击选择文件或拖到这里";

function apiBase() {
  return $("api-base").value.trim().replace(/\/$/, "");
}

function defaultApiBase() {
  if (typeof runtimeConfig.apiBase === "string" && runtimeConfig.apiBase.trim()) {
    return runtimeConfig.apiBase.trim().replace(/\/$/, "");
  }
  const host = window.location.hostname || "127.0.0.1";
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${host}:41000`;
}

function frontendApiKey() {
  return DEFAULT_X_API_KEY;
}

function buildApiHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const apiKey = frontendApiKey();
  if (apiKey) {
    headers["X-API-KEY"] = apiKey;
  }
  return headers;
}

function defaultMineruToken() {
  return typeof runtimeConfig.mineruToken === "string" ? runtimeConfig.mineruToken : "";
}

function defaultModelApiKey() {
  return typeof runtimeConfig.modelApiKey === "string" ? runtimeConfig.modelApiKey : "";
}

function defaultModelName() {
  return typeof runtimeConfig.model === "string" && runtimeConfig.model.trim()
    ? runtimeConfig.model.trim()
    : PROVIDER_PRESETS.deepseek.model;
}

function defaultModelBaseUrl() {
  return typeof runtimeConfig.baseUrl === "string" && runtimeConfig.baseUrl.trim()
    ? runtimeConfig.baseUrl.trim()
    : PROVIDER_PRESETS.deepseek.base_url;
}

function defaultProviderPreset() {
  return typeof runtimeConfig.providerPreset === "string" && runtimeConfig.providerPreset.trim()
    ? runtimeConfig.providerPreset.trim()
    : "deepseek";
}

function applyProviderPreset(presetName, { force = false } = {}) {
  const preset = PROVIDER_PRESETS[presetName];
  if (!preset) {
    return;
  }
  const modelInput = $("model");
  const baseUrlInput = $("base_url");
  const workersInput = $("workers");
  if (force || !modelInput.value.trim()) {
    modelInput.value = preset.model;
  }
  if (force || !baseUrlInput.value.trim()) {
    baseUrlInput.value = preset.base_url;
  }
  if (force || !workersInput.value.trim() || workersInput.value === "0") {
    workersInput.value = preset.workers;
  }
}

function setStatus(status) {
  const el = $("job-status");
  el.textContent = status || "idle";
  el.className = `badge ${status || "idle"}`;
}

function numberOrNull(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function unwrapEnvelope(payload) {
  if (payload && typeof payload === "object" && "data" in payload && "code" in payload) {
    return payload.data;
  }
  return payload;
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function toAbsoluteUrl(value) {
  if (!value || typeof value !== "string") {
    return "";
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }
  if (trimmed.startsWith("/")) {
    return `${apiBase()}${trimmed}`;
  }
  return `${apiBase()}/${trimmed}`;
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "-";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let current = bytes / 1024;
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  return `${current.toFixed(current >= 100 ? 0 : 2)} ${units[unitIndex]}`;
}

function normalizeJobPayload(payload) {
  const unwrapped = unwrapEnvelope(payload) || {};
  const timestamps = unwrapped.timestamps || {};
  const progress = unwrapped.progress || {};
  const artifacts = unwrapped.artifacts || {};
  const status = unwrapped.status || "idle";
  let progressCurrent = numberOrNull(progress.current ?? unwrapped.progress_current);
  let progressTotal = numberOrNull(progress.total ?? unwrapped.progress_total);
  let progressPercent = numberOrNull(progress.percent);

  if (isTerminalStatus(status)) {
    if (progressTotal !== null) {
      progressCurrent = progressTotal;
    }
    if (progressCurrent !== null && progressTotal === null) {
      progressTotal = progressCurrent;
    }
    if (status === "succeeded") {
      progressPercent = 100;
    }
  }

  return {
    raw_response: unwrapped,
    job_id: unwrapped.job_id || "",
    workflow: unwrapped.workflow || unwrapped.job_type || "",
    job_type: unwrapped.job_type || unwrapped.workflow || "",
    status,
    stage: unwrapped.stage || "",
    stage_detail: unwrapped.stage_detail || "",
    progress_current: progressCurrent,
    progress_total: progressTotal,
    progress_percent: progressPercent,
    created_at: timestamps.created_at || unwrapped.created_at || "",
    updated_at: timestamps.updated_at || unwrapped.updated_at || "",
    started_at: timestamps.started_at || unwrapped.started_at || "",
    finished_at: timestamps.finished_at || unwrapped.finished_at || "",
    duration_seconds: numberOrNull(timestamps.duration_seconds ?? unwrapped.duration_seconds),
    links: unwrapped.links || {},
    actions: unwrapped.actions || {},
    artifacts,
    log_tail: Array.isArray(unwrapped.log_tail) ? unwrapped.log_tail : [],
    error: unwrapped.error || "",
    pdf_ready: Boolean(artifacts.pdf_ready ?? artifacts.pdf?.ready),
    markdown_ready: Boolean(artifacts.markdown_ready ?? artifacts.markdown?.ready),
    bundle_ready: Boolean(artifacts.bundle_ready ?? artifacts.bundle?.ready),
  };
}

function resolveJobActions(job) {
  const artifacts = job.artifacts || {};
  const links = job.links || {};
  const actions = job.actions || {};
  const artifactActions = artifacts.actions || {};
  return {
    cancelEnabled: Boolean(actions.cancel?.enabled ?? artifactActions.cancel?.enabled ?? (job.status === "queued" || job.status === "running")),
    bundleEnabled: Boolean(actions.download_bundle?.enabled ?? artifactActions.download_bundle?.enabled ?? job.bundle_ready),
    pdfEnabled: Boolean(actions.download_pdf?.enabled ?? artifactActions.download_pdf?.enabled ?? job.pdf_ready),
    markdownJsonEnabled: Boolean(actions.open_markdown?.enabled ?? artifactActions.open_markdown?.enabled ?? job.markdown_ready),
    markdownRawEnabled: Boolean(actions.open_markdown_raw?.enabled ?? artifactActions.open_markdown_raw?.enabled ?? job.markdown_ready),
    cancel: toAbsoluteUrl(firstNonEmpty(
      actions.cancel?.url,
      artifactActions.cancel?.url,
      actions.cancel_url,
      links.cancel_url,
      links.cancel_path,
    )),
    bundle: toAbsoluteUrl(firstNonEmpty(
      actions.download_bundle?.url,
      artifactActions.download_bundle?.url,
      actions.download_bundle_url,
      actions.bundle_url,
      artifacts.bundle?.url,
      artifacts.bundle?.path,
      artifacts.bundle_url,
    )),
    pdf: toAbsoluteUrl(firstNonEmpty(
      actions.download_pdf?.url,
      artifactActions.download_pdf?.url,
      actions.download_pdf_url,
      actions.pdf_url,
      artifacts.pdf?.url,
      artifacts.pdf?.path,
      artifacts.pdf_url,
    )),
    markdownJson: toAbsoluteUrl(firstNonEmpty(
      actions.open_markdown?.url,
      artifactActions.open_markdown?.url,
      actions.open_markdown_json_url,
      actions.markdown_json_url,
      artifacts.markdown?.json_url,
      artifacts.markdown?.json_path,
      artifacts.markdown_url,
    )),
    markdownRaw: toAbsoluteUrl(firstNonEmpty(
      actions.open_markdown_raw?.url,
      artifactActions.open_markdown_raw?.url,
      actions.download_markdown_url,
      actions.markdown_raw_url,
      artifacts.markdown?.raw_url,
      artifacts.markdown?.raw_path,
    )),
  };
}

function safeJsonClone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function redactCommandArray(command) {
  if (!Array.isArray(command)) {
    return command;
  }
  const redacted = [...command];
  for (let i = 0; i < redacted.length; i += 1) {
    if (redacted[i] === "--api-key" || redacted[i] === "--mineru-token") {
      if (i + 1 < redacted.length) {
        redacted[i + 1] = "***";
      }
    }
  }
  return redacted;
}

function redactSensitive(value) {
  if (Array.isArray(value)) {
    return redactCommandArray(value).map((item) => redactSensitive(item));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const cloned = {};
  for (const [key, raw] of Object.entries(value)) {
    if (["api_key", "mineru_token"].includes(key)) {
      cloned[key] = raw ? "***" : "";
      continue;
    }
    if (key === "command" && Array.isArray(raw)) {
      cloned[key] = redactCommandArray(raw);
      continue;
    }
    cloned[key] = redactSensitive(raw);
  }
  return cloned;
}

function summarizeStatus(status) {
  switch (status) {
    case "queued":
      return "任务已提交，等待后端开始处理。";
    case "running":
      return "任务正在处理中，请等待当前阶段完成。";
    case "succeeded":
      return "任务已完成，可以下载结果。";
    case "canceled":
      return "任务已取消。";
    case "failed":
      return "任务已失败，可重试或进入开发者模式查看内部细节。";
    default:
      return "等待提交任务。";
  }
}

function summarizeStageDetail(payload) {
  const detail = (payload.stage_detail || "").trim();
  if (detail) {
    return detail;
  }
  switch (payload.status) {
    case "queued":
      return "排队中";
    case "running":
      return "后端正在处理当前文档";
    case "succeeded":
      return "处理完成";
    case "failed":
      return "处理失败";
    default:
      return "-";
  }
}

function summarizePublicError(payload) {
  if (payload.status === "canceled") {
    return "任务已取消。";
  }
  if (payload.status === "failed") {
    return "任务失败。可重试；如需定位内部原因，请进入开发者模式查看详细日志。";
  }
  if (payload.error) {
    return "任务返回了错误信息。请稍后重试；如需内部细节，请进入开发者模式查看。";
  }
  return "-";
}

function isTerminalStatus(status) {
  return status === "succeeded" || status === "failed" || status === "canceled";
}

function formatJobFinishedAt(payload) {
  if (!payload || !isTerminalStatus(payload.status)) {
    return "-";
  }
  const rawValue = (payload.finished_at || payload.updated_at || "").trim();
  if (!rawValue) {
    return "-";
  }

  const parsed = new Date(rawValue);
  if (Number.isNaN(parsed.getTime())) {
    return rawValue;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(parsed);
}

function formatJobDuration(payload) {
  if (!payload || !isTerminalStatus(payload.status)) {
    return "-";
  }
  const startedRaw = (payload.started_at || "").trim();
  const finishedRaw = (payload.finished_at || payload.updated_at || "").trim();
  if (!startedRaw || !finishedRaw) {
    return "-";
  }

  const startedAt = new Date(startedRaw);
  const finishedAt = new Date(finishedRaw);
  if (Number.isNaN(startedAt.getTime()) || Number.isNaN(finishedAt.getTime())) {
    return "-";
  }

  const totalSeconds = Math.max(0, Math.round((finishedAt.getTime() - startedAt.getTime()) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}小时 ${minutes}分 ${seconds}秒`;
  }
  if (minutes > 0) {
    return `${minutes}分 ${seconds}秒`;
  }
  return `${seconds}秒`;
}

function setActionLink(id, url, enabled) {
  const el = $(id);
  el.href = enabled && url ? url : "#";
  el.dataset.url = enabled && url ? url : "";
  el.classList.toggle("disabled", !enabled);
  el.setAttribute("aria-disabled", enabled ? "false" : "true");
}

function renderArtifacts(artifacts = {}) {
  const root = $("artifacts");
  root.innerHTML = "";
  const items = [];
  if (artifacts.pdf || artifacts.markdown || artifacts.bundle) {
    items.push(
      ["pdf.ready", artifacts.pdf?.ready ? "true" : "false"],
      ["pdf.file_name", artifacts.pdf?.file_name ?? "-"],
      ["pdf.size_bytes", formatBytes(artifacts.pdf?.size_bytes)],
      ["pdf.path", artifacts.pdf?.path ?? artifacts.pdf_url ?? "-"],
      ["pdf.url", artifacts.pdf?.url ?? "-"],
      ["markdown.ready", artifacts.markdown?.ready ? "true" : "false"],
      ["markdown.file_name", artifacts.markdown?.file_name ?? "-"],
      ["markdown.size_bytes", formatBytes(artifacts.markdown?.size_bytes)],
      ["markdown.json_path", artifacts.markdown?.json_path ?? artifacts.markdown_url ?? "-"],
      ["markdown.raw_path", artifacts.markdown?.raw_path ?? "-"],
      ["bundle.ready", artifacts.bundle?.ready ? "true" : "false"],
      ["bundle.file_name", artifacts.bundle?.file_name ?? "-"],
      ["bundle.size_bytes", formatBytes(artifacts.bundle?.size_bytes)],
      ["bundle.path", artifacts.bundle?.path ?? artifacts.bundle_url ?? "-"],
      ["bundle.url", artifacts.bundle?.url ?? "-"],
    );
  } else {
    for (const key of artifactsOrder) {
      items.push([key, artifacts[key] ?? "-"]);
    }
  }
  for (const [key, value] of items) {
    const wrapper = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = value ?? "-";
    wrapper.appendChild(dt);
    wrapper.appendChild(dd);
    root.appendChild(wrapper);
  }
}

function updateActionButtons(job) {
  const actions = resolveJobActions(job);
  setActionLink("download-btn", actions.bundle, actions.bundleEnabled && !!actions.bundle);
  setActionLink("pdf-btn", actions.pdf, actions.pdfEnabled && !!actions.pdf);
  setActionLink("markdown-btn", actions.markdownJson, actions.markdownJsonEnabled && !!actions.markdownJson);
  setActionLink("markdown-raw-btn", actions.markdownRaw, actions.markdownRawEnabled && !!actions.markdownRaw);
  $("cancel-btn").disabled = !(actions.cancelEnabled && !!actions.cancel);
}

function setLinearProgress(barId, textId, current, total, fallbackText = "-", percentOverride = null) {
  const bar = $(barId);
  const text = $(textId);
  const hasNumbers = Number.isFinite(current) && Number.isFinite(total) && total > 0;
  if (!hasNumbers) {
    bar.style.width = "0%";
    text.textContent = fallbackText;
    return;
  }
  const computedPercent = (current / total) * 100;
  const percent = Math.max(0, Math.min(100, Number.isFinite(percentOverride) ? percentOverride : computedPercent));
  bar.style.width = `${percent}%`;
  text.textContent = `${current} / ${total} (${percent.toFixed(0)}%)`;
}

function setUploadProgress(loaded, total) {
  const panel = $("upload-progress-panel");
  panel.classList.remove("hidden");
  const hasNumbers = Number.isFinite(loaded) && Number.isFinite(total) && total > 0;
  const percent = hasNumbers ? Math.max(0, Math.min(100, (loaded / total) * 100)) : 0;
  $("upload-progress-bar").style.width = `${percent}%`;
  $("upload-progress-text").textContent = hasNumbers ? `${percent.toFixed(0)}%` : "上传中";
}

function resetUploadProgress() {
  $("upload-progress-panel").classList.add("hidden");
  $("upload-progress-bar").style.width = "0%";
  $("upload-progress-text").textContent = "0%";
}

function clearFileInputValue() {
  const input = $("file");
  if (input) {
    input.value = "";
  }
}

function resetUploadedFile() {
  state.uploadId = "";
  state.uploadedFileName = "";
  state.uploadedPageCount = 0;
  state.uploadedBytes = 0;
  $("file").value = "";
  $("submit-btn").disabled = true;
  $("upload-status").textContent = "未上传文件";
  $("file-label").textContent = DEFAULT_FILE_LABEL;
  $("file-label").title = "";
}

function prepareFilePicker() {
  // Safari / iPadOS may not fire change when the same file is chosen again
  // unless the native file input value is cleared before opening the picker.
  clearFileInputValue();
}

function updateDeveloperVisibility() {
  const visible = !!state.developerUnlocked;
  $("developer-log-panel").classList.toggle("hidden", !visible);
  $("developer-details-panel").classList.toggle("hidden", !visible);
}

function updateJobWarning(status) {
  const active = status === "queued" || status === "running";
  $("job-warning").classList.toggle("hidden", !active);
}

function renderJob(payload) {
  const job = normalizeJobPayload(payload);
  const sanitizedPayload = redactSensitive(safeJsonClone(job.raw_response));
  state.currentJobId = job.job_id || state.currentJobId;
  $("job-id").textContent = job.job_id || "-";
  $("job-type").textContent = job.job_type || "-";
  $("job-stage").textContent = job.stage || "-";
  $("job-stage-raw-detail").textContent = job.stage_detail || "-";
  $("job-summary").textContent = summarizeStatus(job.status || "idle");
  $("job-stage-detail").textContent = summarizeStageDetail(job);
  $("job-finished-at").textContent = formatJobFinishedAt(job);
  $("query-job-finished-at").textContent = formatJobFinishedAt(job);
  $("query-job-duration").textContent = formatJobDuration(job);
  $("job-id-input").value = job.job_id || "";
  setStatus(job.status || "idle");
  setLinearProgress(
    "job-progress-bar",
    "job-progress-text",
    job.progress_current,
    job.progress_total,
    "-",
    job.progress_percent,
  );
  $("log-tail").textContent = Array.isArray(job.log_tail) && job.log_tail.length
    ? job.log_tail.join("\n")
    : "-";
  $("error-box").textContent = summarizePublicError(job);
  $("raw-json").textContent = JSON.stringify(sanitizedPayload, null, 2);
  renderArtifacts(job.artifacts || {});
  updateActionButtons(job);
  updateJobWarning(job.status || "idle");
}

function stopPolling() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

async function fetchJob(jobId) {
  const resp = await fetch(`${apiBase()}${API_PREFIX}/jobs/${jobId}`, {
    headers: buildApiHeaders(),
  });
  if (!resp.ok) {
    if (resp.status === 404) {
      throw new Error("未找到该任务，请检查 job_id 是否正确。");
    }
    throw new Error(`读取任务失败，请稍后重试。(${resp.status})`);
  }
  const payload = await resp.json();
  renderJob(payload);
  const job = normalizeJobPayload(payload);
  if (isTerminalStatus(job.status)) {
    stopPolling();
  }
}

function startPolling(jobId) {
  stopPolling();
  state.currentJobId = jobId;
  fetchJob(jobId).catch((err) => {
    $("error-box").textContent = err.message;
  });
  state.timer = setInterval(() => {
    fetchJob(jobId).catch((err) => {
      $("error-box").textContent = err.message;
    });
  }, 3000);
}

function appendIfPresent(form, key, value) {
  if (value === undefined || value === null || value === "") {
    return;
  }
  form.append(key, value);
}

function collectUploadFormData(file) {
  const form = new FormData();
  form.append("file", file);
  form.append("developer_mode", state.developerUnlocked ? "true" : "false");
  return form;
}

function collectRunPayload() {
  return {
    workflow: "mineru",
    upload_id: state.uploadId,
    mode: $("mode").value,
    model: $("model").value.trim() || defaultModelName(),
    base_url: $("base_url").value.trim() || defaultModelBaseUrl(),
    api_key: $("api_key").value || defaultModelApiKey(),
    workers: Number($("workers").value || "0"),
    batch_size: Number($("batch_size").value || "1"),
    classify_batch_size: Number($("classify_batch_size").value || "12"),
    render_mode: $("render_mode").value,
    compile_workers: Number($("compile_workers").value || "0"),
    skip_title_translation: $("skip_title_translation").checked,
    mineru_token: $("mineru_token").value || defaultMineruToken(),
    model_version: $("model_version").value,
    language: $("language").value.trim(),
    page_ranges: $("page_ranges").value.trim(),
    rule_profile_name: $("rule_profile_name").value,
    custom_rules_text: $("custom_rules_text").value,
  };
}

function submitUploadRequest(url, form) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";
    const apiKey = frontendApiKey();
    if (apiKey) {
      xhr.setRequestHeader("X-API-KEY", apiKey);
    }

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        setUploadProgress(event.loaded, event.total);
      } else {
        setUploadProgress(NaN, NaN);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(unwrapEnvelope(xhr.response));
        return;
      }
      const message = typeof xhr.response === "object" && xhr.response
        ? (xhr.response.message || JSON.stringify(xhr.response))
        : (xhr.responseText || "");
      reject(new Error(`提交失败: ${xhr.status} ${message}`));
    });

    xhr.addEventListener("error", () => {
      reject(new Error(`提交失败: 网络错误。当前 API Base 为 ${apiBase()}，上传地址为 ${url}。请检查 41000 端口是否可从浏览器访问，或强制刷新前端缓存后再试。`));
    });

    xhr.send(form);
  });
}

async function submitJson(url, payload) {
  const resp = await fetch(url, {
    method: "POST",
    headers: buildApiHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const errorPayload = await resp.json();
      throw new Error(`提交失败: ${resp.status} ${errorPayload.message || JSON.stringify(errorPayload)}`);
    }
    const text = await resp.text();
    throw new Error(`提交失败: ${resp.status} ${text}`);
  }
  const payloadJson = await resp.json();
  return unwrapEnvelope(payloadJson);
}

async function fetchProtected(url, options = {}) {
  const headers = buildApiHeaders(options.headers || {});
  return fetch(url, {
    ...options,
    headers,
  });
}

function fileNameFromDisposition(disposition, fallback) {
  if (!disposition || typeof disposition !== "string") {
    return fallback;
  }
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch (_err) {
      return utf8Match[1];
    }
  }
  const plainMatch = disposition.match(/filename=\"?([^\";]+)\"?/i);
  return plainMatch && plainMatch[1] ? plainMatch[1] : fallback;
}

function downloadBlob(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

function openBlob(blob, popup = null) {
  const objectUrl = URL.createObjectURL(blob);
  if (popup && !popup.closed) {
    popup.location.href = objectUrl;
  } else {
    window.open(objectUrl, "_blank", "noopener,noreferrer");
  }
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

async function handleProtectedArtifactClick(event) {
  const link = event.currentTarget;
  const disabled = link.classList.contains("disabled") || link.getAttribute("aria-disabled") === "true";
  const url = link.dataset.url || "";
  if (disabled || !url) {
    event.preventDefault();
    return;
  }

  event.preventDefault();
  $("error-box").textContent = "-";
  const shouldOpenInline = link.id === "pdf-btn" || link.id === "markdown-btn";
  const popup = shouldOpenInline ? window.open("", "_blank", "noopener,noreferrer") : null;

  try {
    const resp = await fetchProtected(url);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`下载失败: ${resp.status} ${text || "unknown error"}`);
    }

    const blob = await resp.blob();
    const disposition = resp.headers.get("content-disposition") || "";
    const jobId = $("job-id-input").value.trim() || state.currentJobId || "result";
    const fallbackName = link.id === "download-btn"
      ? `${jobId}.zip`
      : link.id === "pdf-btn"
        ? `${jobId}.pdf`
        : link.id === "markdown-raw-btn"
          ? `${jobId}.md`
          : `${jobId}.json`;
    const fileName = fileNameFromDisposition(disposition, fallbackName);

    if (link.id === "download-btn" || link.id === "markdown-raw-btn") {
      downloadBlob(blob, fileName);
      return;
    }
    openBlob(blob, popup);
  } catch (err) {
    if (popup && !popup.closed) {
      popup.close();
    }
    $("error-box").textContent = err.message;
  }
}

async function handleFileSelected() {
  const file = $("file").files[0];
  resetUploadedFile();
  resetUploadProgress();
  $("file-label").textContent = file ? file.name : DEFAULT_FILE_LABEL;
  $("file-label").title = file ? file.name : "";
  if (!file) {
    return;
  }
  if (!state.developerUnlocked && file.size > 10 * 1024 * 1024) {
    $("error-box").textContent = "普通用户仅支持 10MB 以内 PDF";
    $("upload-status").textContent = "文件超出普通用户大小限制";
    return;
  }
  $("error-box").textContent = "-";
  $("upload-status").textContent = "正在上传…";

  try {
    const payload = await submitUploadRequest(`${apiBase()}${API_PREFIX}/uploads`, collectUploadFormData(file));
    state.uploadId = payload.upload_id || "";
    state.uploadedFileName = payload.filename || file.name;
    state.uploadedPageCount = Number(payload.page_count || 0);
    state.uploadedBytes = Number(payload.bytes || file.size || 0);
    $("submit-btn").disabled = !state.uploadId;
    $("upload-status").textContent = `上传完成: ${state.uploadedFileName} | ${state.uploadedPageCount} 页 | ${(state.uploadedBytes / 1024 / 1024).toFixed(2)} MB`;
    clearFileInputValue();
  } catch (err) {
    resetUploadedFile();
    clearFileInputValue();
    $("error-box").textContent = err.message;
    $("upload-status").textContent = "上传失败";
  }
}

async function submitForm(event) {
  event.preventDefault();
  if (!state.uploadId) {
    $("error-box").textContent = "请先选择并上传 PDF 文件";
    return;
  }

  $("submit-btn").disabled = true;
  $("error-box").textContent = "-";

  try {
    const payload = await submitJson(`${apiBase()}${API_PREFIX}/jobs`, collectRunPayload());
    $("job-id").textContent = payload.job_id || "-";
    $("job-id-input").value = payload.job_id || "";
    setStatus(payload.status || "queued");
    $("job-summary").textContent = summarizeStatus(payload.status || "queued");
    $("job-stage-detail").textContent = payload.status === "queued" ? "任务已提交，等待后端开始处理。" : "-";
    $("job-finished-at").textContent = "-";
    $("query-job-finished-at").textContent = "-";
    $("query-job-duration").textContent = "-";
    $("raw-json").textContent = JSON.stringify(redactSensitive(safeJsonClone(payload)), null, 2);
    updateActionButtons(normalizeJobPayload(payload));
    startPolling(payload.job_id);
  } catch (err) {
    $("error-box").textContent = err.message;
  } finally {
    $("submit-btn").disabled = false;
  }
}

function watchExistingJob() {
  const jobId = $("job-id-input").value.trim();
  if (!jobId) {
    $("error-box").textContent = "请输入 job_id";
    return;
  }
  startPolling(jobId);
}

async function cancelCurrentJob() {
  const jobId = $("job-id-input").value.trim() || state.currentJobId;
  if (!jobId) {
    $("error-box").textContent = "当前没有可取消的任务";
    return;
  }
  $("cancel-btn").disabled = true;
  try {
    await submitJson(`${apiBase()}${API_PREFIX}/jobs/${jobId}/cancel`, {});
    await fetchJob(jobId);
  } catch (err) {
    $("error-box").textContent = err.message;
  }
}

function openDeveloperAccess() {
  if (state.developerUnlocked) {
    $("developer-dialog").showModal();
    return;
  }
  $("developer-password").value = "";
  $("developer-auth-error").classList.add("hidden");
  $("developer-auth-dialog").showModal();
}

function submitDeveloperPassword() {
  if ($("developer-password").value === DEVELOPER_PASSWORD) {
    state.developerUnlocked = true;
    updateDeveloperVisibility();
    $("developer-auth-dialog").close();
    $("developer-dialog").showModal();
    return;
  }
  $("developer-auth-error").classList.remove("hidden");
}

async function loadRuleProfiles() {
  const select = $("rule_profile_name");
  const current = select.value;
  select.innerHTML = "";
  for (const item of BUILTIN_RULE_PROFILES) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.label;
    if (item.name === current) {
      option.selected = true;
    }
    select.appendChild(option);
  }
  if (![...select.options].some((option) => option.selected) && select.options.length) {
    select.options[0].selected = true;
  }
}

async function checkApiConnectivity() {
  try {
    const resp = await fetch(`${apiBase()}/health`);
    if (!resp.ok) {
      throw new Error(`health ${resp.status}`);
    }
  } catch (_err) {
    $("error-box").textContent = `当前前端无法连接后端。API Base: ${apiBase()}。如果你是远程访问页面，请确认浏览器能直接访问 41000 端口；如果刚更新过前端，请先强制刷新页面。`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  if (!$("api-base").value.trim()) {
    $("api-base").value = defaultApiBase();
  }
  const providerPreset = defaultProviderPreset();
  if ([...$("provider_preset").options].some((option) => option.value === providerPreset)) {
    $("provider_preset").value = providerPreset;
  }
  applyProviderPreset($("provider_preset").value, { force: true });
  if (!$("model").value.trim()) {
    $("model").value = defaultModelName();
  }
  if (!$("base_url").value.trim()) {
    $("base_url").value = defaultModelBaseUrl();
  }
  $("file").addEventListener("click", prepareFilePicker);
  $("file").addEventListener("change", handleFileSelected);
  $("developer-btn").addEventListener("click", openDeveloperAccess);
  $("developer-auth-submit-btn").addEventListener("click", submitDeveloperPassword);
  $("provider_preset").addEventListener("change", (event) => {
    const value = event.target.value;
    if (value === "custom") {
      return;
    }
    applyProviderPreset(value, { force: true });
  });
  $("developer-password").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submitDeveloperPassword();
    }
  });
  $("job-form").addEventListener("submit", submitForm);
  $("watch-btn").addEventListener("click", watchExistingJob);
  $("cancel-btn").addEventListener("click", cancelCurrentJob);
  $("stop-btn").addEventListener("click", stopPolling);
  $("download-btn").addEventListener("click", handleProtectedArtifactClick);
  $("pdf-btn").addEventListener("click", handleProtectedArtifactClick);
  $("markdown-btn").addEventListener("click", handleProtectedArtifactClick);
  $("markdown-raw-btn").addEventListener("click", handleProtectedArtifactClick);
  renderArtifacts({});
  updateActionButtons(normalizeJobPayload({}));
  setLinearProgress("job-progress-bar", "job-progress-text", NaN, NaN, "-");
  $("job-summary").textContent = summarizeStatus("idle");
  $("job-stage-detail").textContent = "-";
  $("query-job-finished-at").textContent = "-";
  $("query-job-duration").textContent = "-";
  resetUploadProgress();
  resetUploadedFile();
  updateDeveloperVisibility();
  updateJobWarning("idle");
  loadRuleProfiles().catch(() => {});
  checkApiConnectivity().catch(() => {});
});
