/* Document Database Builder — UI logic.
   Plain JS, no build step, no external dependencies (works air-gapped). */

"use strict";

const API = "/api/v1";
const KEY_STORAGE = "vdb_api_key";

const $ = (id) => document.getElementById(id);
const els = {
  viewConnect: $("view-connect"),
  viewApp: $("view-app"),
  toasts: $("toasts"),
};

let apiKey = null;
let tenant = null;
let uploadQueue = []; // {file, state: 'pending'|'busy'|'ok'|'err', message}

/* ── Helpers ─────────────────────────────────────────────── */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(message, kind = "info") {
  const el = document.createElement("div");
  el.className = `toast ${kind === "error" ? "err" : kind === "ok" ? "ok" : ""}`;
  el.textContent = message;
  els.toasts.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const res = await fetch(API + path, { ...options, headers });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) detail = data.detail[0].msg;
    } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res;
}

const apiJson = async (path, options) => (await api(path, options)).json();

async function downloadFile(path, fallbackName) {
  const res = await api(path);
  const blob = await res.blob();
  const dispo = res.headers.get("Content-Disposition") || "";
  const match = dispo.match(/filename="?([^";]+)"?/);
  const name = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function copyText(text, button) {
  const done = () => {
    if (!button) return;
    const old = button.textContent;
    button.textContent = "Copied!";
    setTimeout(() => (button.textContent = old), 1500);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done, () => legacyCopy(text, done));
  } else {
    legacyCopy(text, done); // plain-HTTP LAN deployments have no clipboard API
  }
}

function legacyCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch { toast("Copy failed — select the key and copy it manually", "error"); }
  ta.remove();
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-copy-target]");
  if (btn) copyText($(btn.dataset.copyTarget).textContent, btn);
});

const fmtBytes = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB`
  : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n} B`;

const fmtDate = (iso) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

const OUTPUT_LABELS = { vector: "Smart search", markdown: "Markdown", sqlite: "SQLite" };

/* ── View switching ──────────────────────────────────────── */

function showConnect() {
  els.viewApp.classList.add("hidden");
  els.viewConnect.classList.remove("hidden");
}

async function showApp() {
  tenant = await apiJson("/tenants/me");
  els.viewConnect.classList.add("hidden");
  els.viewApp.classList.remove("hidden");

  $("tenant-name").textContent = tenant.name;
  const badge = $("scope-badge");
  const isAdmin = tenant.scope === "admin";
  badge.textContent = isAdmin ? "Admin" : "Retrieval";
  badge.className = `badge ${isAdmin ? "admin" : ""}`;

  document.querySelectorAll(".admin-only").forEach((el) => el.classList.toggle("hidden", !isAdmin));
  $("card-retrieval-note").classList.toggle("hidden", isAdmin);

  $("stat-chunks").textContent = tenant.total_chunks;
  if (isAdmin) {
    await Promise.all([refreshDocuments(), refreshKeys()]);
  } else {
    $("stat-docs").textContent = tenant.document_count;
    $("stat-ready").textContent = "–";
  }
}

async function boot() {
  apiKey = localStorage.getItem(KEY_STORAGE);
  if (!apiKey) return showConnect();
  try {
    await showApp();
  } catch {
    localStorage.removeItem(KEY_STORAGE);
    apiKey = null;
    showConnect();
  }
}

/* ── Connect screen ──────────────────────────────────────── */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    $("form-create").classList.toggle("hidden", tab.dataset.tab !== "create");
    $("form-connect").classList.toggle("hidden", tab.dataset.tab !== "connect");
    $("key-reveal").classList.add("hidden");
  });
});

$("create-name").addEventListener("input", (e) => {
  const slug = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  $("create-slug").value = slug;
});

$("form-create").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const data = await apiJson("/tenants", {
      method: "POST",
      json: { name: $("create-name").value.trim(), slug: $("create-slug").value.trim() },
    });
    apiKey = data.admin_api_key;
    $("new-admin-key").textContent = data.admin_api_key;
    $("form-create").classList.add("hidden");
    $("form-connect").classList.add("hidden");
    document.querySelector(".tabs").classList.add("hidden");
    $("key-reveal").classList.remove("hidden");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
});

$("key-reveal-continue").addEventListener("click", async () => {
  localStorage.setItem(KEY_STORAGE, apiKey);
  $("new-admin-key").textContent = "";
  try { await showApp(); } catch (err) { toast(err.message, "error"); }
});

$("form-connect").addEventListener("submit", async (e) => {
  e.preventDefault();
  apiKey = $("connect-key").value.trim();
  try {
    await showApp();
    localStorage.setItem(KEY_STORAGE, apiKey);
    $("connect-key").value = "";
  } catch (err) {
    apiKey = null;
    toast(err.message === "Invalid or inactive API key" ? "That key wasn't recognized — check it and try again." : err.message, "error");
  }
});

$("btn-disconnect").addEventListener("click", () => {
  localStorage.removeItem(KEY_STORAGE);
  apiKey = null;
  tenant = null;
  document.querySelector(".tabs").classList.remove("hidden");
  $("form-connect").classList.remove("hidden");
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === "connect"));
  $("form-create").classList.add("hidden");
  showConnect();
});

/* ── Upload ──────────────────────────────────────────────── */

const dropzone = $("dropzone");
const fileInput = $("file-input");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
$("btn-browse").addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });
fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });

["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

const ALLOWED = [".pdf", ".docx", ".txt", ".csv", ".md"];

function addFiles(fileList) {
  for (const file of fileList) {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!ALLOWED.includes(ext)) {
      toast(`"${file.name}" skipped — supported types: PDF, DOCX, TXT, CSV, MD`, "error");
      continue;
    }
    if (file.size > 50 * 1048576) {
      toast(`"${file.name}" skipped — larger than 50 MB`, "error");
      continue;
    }
    uploadQueue.push({ file, state: "pending", message: "" });
  }
  renderUploadQueue();
}

function renderUploadQueue() {
  const ul = $("upload-list");
  ul.innerHTML = uploadQueue.map((item, i) => `
    <li class="upload-item">
      <span class="fname" title="${esc(item.file.name)}">${esc(item.file.name)}</span>
      <span class="muted small">${fmtBytes(item.file.size)}</span>
      ${item.state === "busy" ? '<span class="fstate busy"><span class="spin"></span> building…</span>' : ""}
      ${item.state === "ok" ? '<span class="fstate ok">✓ done</span>' : ""}
      ${item.state === "err" ? `<span class="fstate err" title="${esc(item.message)}">✗ ${esc(item.message)}</span>` : ""}
      ${item.state === "pending" ? `<button class="rm" data-rm="${i}" title="Remove" aria-label="Remove ${esc(item.file.name)}">✕</button>` : ""}
    </li>`).join("");
  ul.querySelectorAll("[data-rm]").forEach((btn) =>
    btn.addEventListener("click", () => { uploadQueue.splice(Number(btn.dataset.rm), 1); renderUploadQueue(); }));
  updateUploadButton();
}

function selectedOutputs() {
  const outputs = [];
  if ($("out-vector").checked) outputs.push("vector");
  if ($("out-markdown").checked) outputs.push("markdown");
  if ($("out-sqlite").checked) outputs.push("sqlite");
  return outputs;
}

function updateUploadButton() {
  const pending = uploadQueue.filter((i) => i.state === "pending").length;
  const btn = $("btn-upload");
  btn.disabled = pending === 0 || selectedOutputs().length === 0;
  btn.textContent = pending > 1 ? `Upload & build ${pending} files` : "Upload & build";
}

["out-vector", "out-markdown", "out-sqlite"].forEach((id) => $(id).addEventListener("change", updateUploadButton));

$("btn-upload").addEventListener("click", async () => {
  const outputs = selectedOutputs().join(",");
  $("btn-upload").disabled = true;

  for (const item of uploadQueue) {
    if (item.state !== "pending") continue;
    item.state = "busy";
    renderUploadQueue();
    try {
      const form = new FormData();
      form.append("file", item.file);
      form.append("outputs", outputs);
      const doc = await apiJson("/documents/upload", { method: "POST", body: form });
      if (doc.status === "failed") {
        item.state = "err";
        item.message = doc.error_message || "processing failed";
      } else {
        item.state = "ok";
      }
    } catch (err) {
      item.state = "err";
      item.message = err.message;
    }
    renderUploadQueue();
  }

  const ok = uploadQueue.filter((i) => i.state === "ok").length;
  const failed = uploadQueue.filter((i) => i.state === "err").length;
  if (ok) toast(`${ok} document${ok > 1 ? "s" : ""} ready to use`, "ok");
  if (failed) toast(`${failed} upload${failed > 1 ? "s" : ""} failed — see the list for details`, "error");

  // Keep failures visible; clear successes after a moment
  setTimeout(() => {
    uploadQueue = uploadQueue.filter((i) => i.state !== "ok");
    renderUploadQueue();
  }, 2500);

  await Promise.all([refreshDocuments(), refreshStats()]);
  updateUploadButton();
});

/* ── Documents ───────────────────────────────────────────── */

async function refreshStats() {
  try {
    tenant = await apiJson("/tenants/me");
    $("stat-chunks").textContent = tenant.total_chunks;
  } catch { /* non-critical */ }
}

async function refreshDocuments() {
  const data = await apiJson("/documents");
  const docs = data.documents;
  $("stat-docs").textContent = docs.length;
  $("stat-ready").textContent = docs.filter((d) => d.status === "ready").length;

  $("docs-empty").classList.toggle("hidden", docs.length > 0);
  $("docs-table").classList.toggle("hidden", docs.length === 0);

  $("docs-tbody").innerHTML = docs.map((d) => {
    const outputs = d.output_formats.map((f) => `<span class="badge gray">${OUTPUT_LABELS[f] || esc(f)}</span>`).join("");
    const canMd = d.status === "ready" && d.output_formats.includes("markdown");
    const canDb = d.status === "ready" && d.output_formats.includes("sqlite");
    const statusLabel = d.status === "ready" ? "Ready" : d.status === "failed" ? "Failed" : "Processing";
    return `<tr>
      <td>
        <div class="doc-name" title="${esc(d.filename)}">${esc(d.filename)}</div>
        <div class="doc-sub">${esc(d.file_type.toUpperCase())} · added ${fmtDate(d.created_at)}</div>
      </td>
      <td><span class="status ${esc(d.status)}">${statusLabel}</span></td>
      <td><div class="badges">${outputs}</div></td>
      <td>${fmtBytes(d.file_size_bytes)}</td>
      <td class="cell-actions">
        ${canMd ? `<button class="btn btn-ghost btn-sm" data-dl="${d.id}" data-fmt="markdown" title="Download Markdown file">.md</button>` : ""}
        ${canDb ? `<button class="btn btn-ghost btn-sm" data-dl="${d.id}" data-fmt="sqlite" title="Download SQLite database file">.db</button>` : ""}
        <button class="btn btn-danger-ghost btn-sm" data-del="${d.id}" data-name="${esc(d.filename)}" title="Delete document">Delete</button>
      </td>
    </tr>`;
  }).join("");

  $("docs-tbody").querySelectorAll("[data-dl]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await downloadFile(`/documents/${btn.dataset.dl}/export/${btn.dataset.fmt}`, `export.${btn.dataset.fmt === "sqlite" ? "db" : "md"}`);
      } catch (err) { toast(err.message, "error"); }
      btn.disabled = false;
    }));

  $("docs-tbody").querySelectorAll("[data-del]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm(`Delete "${btn.dataset.name}" and everything built from it? This cannot be undone.`)) return;
      try {
        await api(`/documents/${btn.dataset.del}`, { method: "DELETE" });
        toast("Document deleted", "ok");
        await Promise.all([refreshDocuments(), refreshStats()]);
      } catch (err) { toast(err.message, "error"); }
    }));
}

$("btn-export-sqlite").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try { await downloadFile("/export/sqlite", "documents.db"); }
  catch (err) { toast(err.message, "error"); }
  e.target.disabled = false;
});

$("btn-export-markdown").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try { await downloadFile("/export/markdown", "documents.md"); }
  catch (err) { toast(err.message, "error"); }
  e.target.disabled = false;
});

/* ── Search ──────────────────────────────────────────────── */

$("form-search").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  const results = $("search-results");
  btn.disabled = true;
  results.innerHTML = '<p class="muted"><span class="spin"></span> Searching…</p>';
  try {
    const mode = e.target.querySelector("input[name=mode]:checked").value;
    const data = await apiJson("/retrieve", {
      method: "POST",
      json: { query: $("search-query").value, top_k: 5, mode },
    });
    if (!data.snippets.length) {
      results.innerHTML = `<p class="muted">No matches. ${mode === "semantic"
        ? "Try the <strong>Exact</strong> mode for error codes, or check that your documents were built with the smart search database."
        : "Try different words, or the <strong>Smart</strong> mode for natural-language questions."}</p>`;
      return;
    }
    results.innerHTML = data.snippets.map((s) => {
      const pct = Math.max(0, Math.min(100, Math.round(s.relevance_score * 100)));
      return `<article class="snippet">
        <div class="snippet-meta">
          <span class="snippet-src" title="${esc(s.source_filename)}">${esc(s.source_filename)}</span>
          <span class="score"><span class="score-bar"><i style="width:${pct}%"></i></span>${pct}%</span>
        </div>
        <p class="snippet-text">${esc(s.content)}</p>
      </article>`;
    }).join("");
  } catch (err) {
    results.innerHTML = "";
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
});

/* ── API keys ────────────────────────────────────────────── */

async function refreshKeys() {
  const keys = await apiJson("/tenants/keys");
  $("keys-tbody").innerHTML = keys.map((k) => `<tr>
    <td>${esc(k.label)}</td>
    <td><span class="badge ${k.scope === "admin" ? "admin" : ""}">${k.scope === "admin" ? "Admin" : "Retrieval"}</span></td>
    <td class="muted">${fmtDate(k.created_at)}</td>
  </tr>`).join("");
}

$("form-key").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  try {
    const data = await apiJson("/tenants/keys", {
      method: "POST",
      json: { label: $("key-label").value.trim(), scope: $("key-scope").value },
    });
    $("fresh-key-value").textContent = data.api_key;
    $("fresh-key").classList.remove("hidden");
    $("key-label").value = "";
    await refreshKeys();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
});

/* ── Go ──────────────────────────────────────────────────── */

boot();
