import {
  parseYaml,
  dumpComponent,
  normalizeComponent,
  validateComponent,
  nextFeatureId,
  utf8ToBase64,
  applyBatch,
  sameFeature,
  batchCommitMessage,
} from "./model.js";
import { statusSet, statusInfo, tally, noteKeyFor, noteOrder, noun, countNoun, isRequirement, testColumn, coverage, excluded, included, done, riskDone, risky, coverageLevel, riskLevel, notSupportedLevel } from "./template.js";

const DEFAULT_REPO = { name: "", branch: "main", path: "matrix-table/data", tag_prefix: "matrix-table/" };
const LS = "matrixTable.";
const $ = (selector, root = document) => root.querySelector(selector);
// Present only in a standalone report produced by "Export HTML".
const EMBEDDED = document.getElementById("embedded-data");
const VERSION = new URLSearchParams(location.search).get("v");

const state = {
  meta: null,
  components: [], // [{ path, sha, doc, base }]
  index: new Map(), // feature id -> { entry, feature }
  source: null, // "live" | "snapshot" | "export"
  generated: null,
  versions: [], // [{ name, tag, date, tagger, message }]
  version: null, // the version being viewed, null = latest
  user: null,
  focus: localStorage.getItem(`${LS}focus`),
  settings: JSON.parse(localStorage.getItem(`${LS}settings`) || "{}"),
  filter: { status: "", text: "" },
  draft: null,
  saving: false,
  selection: new Set(), // feature ids ticked for a batch status change
  batch: { column: null, value: null, note: "" },
  visibleIds: [],
};

// ---------------------------------------------------------------- helpers

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
const clone = (value) => JSON.parse(JSON.stringify(value));
const statusOf = (feature, column) => feature.status?.[column] || "unset";
const columnOf = (column) => (typeof column === "string" ? state.meta.columns.find((c) => c.id === column) : column);
const setOf = (column) => statusSet(state.meta, columnOf(column));
const openIds = (column) => setOf(column).filter((s) => !s.resolved).map((s) => s.id);
const notDoneIds = (column) => [...openIds(column), "unset"];
const statusLabel = (column, value) => statusInfo(state.meta, columnOf(column), value).label;
const statusTitle = (column, value) => statusInfo(state.meta, columnOf(column), value).title;
const pill = (column, value) => {
  const info = statusInfo(state.meta, columnOf(column), value);
  return `<span class="pill ${info.cls}" title="${esc(info.title)}">${esc(info.label)}</span>`;
};
const isReq = () => isRequirement(state.meta);
const word = (n) => noun(state.meta, n);
const cap = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const filterFields = () => (isReq() ? (state.meta.fields ?? []).filter((f) => f.filter && f.type === "enum") : []);
const fieldFilters = (params = route().params) => Object.fromEntries(filterFields().map((f) => [f.id, params.get(f.id) ?? ""]));
const tableFields = () => (isReq() ? (state.meta.fields ?? []).filter((f) => f.show === "table") : []);
const keepQuery = () => {
  const params = new URLSearchParams();
  for (const [id, value] of Object.entries(fieldFilters())) if (value) params.set(id, value);
  return params.toString();
};
const fieldValue = (f, item) => {
  const v = item.fields?.[f.id];
  if (v === undefined || v === null || v === "") return "";
  return f.type === "enum" ? (f.values?.find((x) => x.id === v)?.label ?? v) : Array.isArray(v) ? v.join(", ") : String(v);
};
const platformName = (id) => (state.meta.platforms.find((p) => p.id === id)?.name ?? id);
const noteName = (key) => state.meta.note_keys?.find((k) => k.id === key)?.name ?? platformName(key);
const isDefaultColumn = (column) => !columnOf(column)?.status_set || columnOf(column).status_set === "default";
const TONE_BAR = { yes: "var(--yes-bar)", no: "var(--no-bar)", open: "var(--tbd-bar)", neutral: "var(--tone-neutral-bar)", info: "var(--tone-info-bar)", warn: "var(--tone-warn-bar)" };
const sectionOf = (componentId) => state.meta.sections.find((s) => s.id === componentId.split(".")[0]);
const componentEntry = (id) => state.components.find((c) => c.doc.id === id);
const canEdit = () => state.source === "live" && state.settings.token && !state.version;

function columnTitle(column) {
  return column.platform ? `${platformName(column.platform)} · ${column.name}` : column.name;
}

function repo() {
  const fromMeta = state.meta?.repository ?? {};
  return {
    name: state.settings.repo || fromMeta.name || DEFAULT_REPO.name,
    branch: state.settings.branch || fromMeta.branch || DEFAULT_REPO.branch,
    path: fromMeta.path || DEFAULT_REPO.path,
    tagPrefix: fromMeta.tag_prefix || DEFAULT_REPO.tag_prefix,
  };
}

function counts(features, column = state.focus) {
  return tally(isReq() ? included(features, state.meta) : features, state.meta, columnOf(column));
}
const notDone = (c) => c.open + c.unset;
const isExcluded = (item) => isReq() && excluded(state.meta, item);

function allFeatures() {
  return state.components.flatMap((entry) => entry.doc.features);
}

function jiraKeys(text) {
  const projects = state.meta.jira_projects ?? [];
  if (!projects.length || !text) return [];
  const re = new RegExp(`\\b(?:${projects.join("|")})-\\d+\\b`, "g");
  return [...new Set(String(text).match(re) ?? [])];
}

function featureJira(feature) {
  return jiraKeys([feature.comment, ...Object.values(feature.notes ?? {})].join("\n"));
}

function linkify(text) {
  let html = esc(text);
  html = html.replace(/https?:\/\/[^\s<>"')]+/g, (url) => `<a href="${url}" target="_blank" rel="noopener">${url}</a>`);
  const projects = state.meta.jira_projects ?? [];
  if (projects.length && state.meta.jira_url) {
    const re = new RegExp(`(^|[^\\w/-])((?:${projects.join("|")})-\\d+)\\b`, "g");
    html = html.replace(re, (_, pre, key) => `${pre}<a class="jira" href="${esc(state.meta.jira_url + key)}" target="_blank" rel="noopener">${key}</a>`);
  }
  return html;
}

function columnGroups() {
  const groups = [];
  for (const column of state.meta.columns) {
    const label = column.platform ? platformName(column.platform) : (column.group ?? "");
    const last = groups.at(-1);
    if (last && last.label === label) last.columns.push(column);
    else groups.push({ label, platform: column.platform, columns: [column] });
  }
  return groups;
}

function toast(html, kind = "") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.innerHTML = html;
  $("#toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 9000 : 5000);
}

function decodeBase64(b64) {
  const binary = atob(b64.replace(/\s/g, ""));
  return new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
}

function githubUrl(kind, path = "") {
  const { name, branch } = repo();
  return `https://github.com/${name}/${kind}/${encodeURIComponent(branch).replace(/%2F/g, "/")}/${path}`;
}

// ---------------------------------------------------------------- GitHub API

async function gh(path, { method = "GET", body, cache = "no-store" } = {}) {
  const res = await fetch(`https://api.github.com${path}`, {
    method,
    cache,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${state.settings.token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = (await res.json()).message || message;
    } catch {
      /* not JSON */
    }
    const error = new Error(`GitHub ${res.status}: ${message}`);
    error.status = res.status;
    throw error;
  }
  return res.status === 204 ? null : res.json();
}

const encodePath = (path) => path.split("/").map(encodeURIComponent).join("/");

/** File text at `ref`. The Contents API leaves `content` empty above 1 MB; read those as blobs. */
async function readFileAt(path, ref) {
  const { name } = repo();
  const file = await gh(`/repos/${name}/contents/${encodePath(path)}?ref=${encodeURIComponent(ref)}`);
  const b64 = file.content || (await gh(`/repos/${name}/git/blobs/${file.sha}`, { cache: "default" })).content;
  return { sha: file.sha, text: decodeBase64(b64) };
}

async function loadLive() {
  const { name, branch, path, tagPrefix } = repo();
  state.versions = await listLiveVersions().catch((e) => {
    toast(`Could not list versions: ${esc(e.message)}`, "error");
    return [];
  });
  const version = VERSION ? state.versions.find((v) => v.name === VERSION) : null;
  if (VERSION && !version) toast(`Version “${esc(VERSION)}” not found — showing latest`, "error");
  const ref = version ? `${tagPrefix}${version.name}` : branch;
  const listing = await gh(`/repos/${name}/contents/${encodePath(path)}?ref=${encodeURIComponent(ref)}`);
  const files = listing.filter((f) => f.type === "file" && f.name.endsWith(".yaml"));
  const loaded = await Promise.all(
    files.map(async (file) => {
      const blob = await gh(`/repos/${name}/git/blobs/${file.sha}`, { cache: "default" });
      return { ...file, text: decodeBase64(blob.content) };
    }),
  );
  const metaFile = loaded.find((f) => f.name === "_meta.yaml");
  if (!metaFile) throw new Error(`_meta.yaml not found in ${name}@${ref}:${path}`);
  state.meta = parseYaml(metaFile.text);
  state.components = loaded
    .filter((f) => !f.name.startsWith("_"))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((f) => {
      const doc = parseYaml(f.text);
      return { path: f.path, sha: f.sha, doc, base: clone(doc) };
    });
  state.source = "live";
  state.version = version;
  state.generated = new Date();
}

async function listLiveVersions() {
  const { name, tagPrefix } = repo();
  const refs = await gh(`/repos/${name}/git/matching-refs/${encodePath(`tags/${tagPrefix}`)}`);
  const versions = await Promise.all(
    refs.map(async (ref) => {
      const tag = ref.ref.replace(/^refs\/tags\//, "");
      const version = { name: tag.slice(tagPrefix.length), tag };
      if (ref.object.type === "tag") {
        const info = await gh(`/repos/${name}/git/tags/${ref.object.sha}`, { cache: "default" });
        Object.assign(version, { date: info.tagger?.date, tagger: info.tagger?.name, message: info.message?.trim() });
      } else {
        const info = await gh(`/repos/${name}/git/commits/${ref.object.sha}`, { cache: "default" });
        Object.assign(version, { date: info.committer?.date, tagger: info.committer?.name, message: "" });
      }
      return version;
    }),
  );
  return versions.sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

async function loadSnapshot() {
  const res = await fetch("data.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`data.json: HTTP ${res.status}`);
  let data = await res.json();
  state.versions = data.versions ?? [];
  const version = VERSION ? state.versions.find((v) => v.name === VERSION) : null;
  if (VERSION && !version && !state.settings.token) toast(`Version “${esc(VERSION)}” not found — showing latest`, "error");
  if (version) {
    const versionRes = await fetch(`versions/${encodeURIComponent(version.file)}`, { cache: "no-store" });
    if (!versionRes.ok) throw new Error(`${version.file}: HTTP ${versionRes.status}`);
    data = { ...data, ...(await versionRes.json()) };
  }
  state.meta = data.meta;
  state.components = data.components.map((c) => ({ ...c, base: clone(c.doc) }));
  state.source = "snapshot";
  state.version = version;
  state.generated = new Date(data.generated);
}

function loadEmbedded() {
  const data = JSON.parse(EMBEDDED.textContent);
  state.meta = data.meta;
  state.components = data.components.map((c) => ({ ...c, base: c.doc }));
  state.source = "export";
  state.version = data.version;
  state.versions = data.version ? [data.version] : [];
  state.generated = new Date(data.generated);
}

async function load() {
  $("#content").innerHTML = `<div class="loading">Loading matrix table…</div>`;
  if (EMBEDDED) {
    loadEmbedded();
  } else {
    let snapshotError;
    try {
      await loadSnapshot();
    } catch (e) {
      snapshotError = e;
    }
    if (state.settings.token) {
      try {
        await loadLive();
      } catch (e) {
        toast(`Live data unavailable: ${esc(e.message)}${state.meta ? " — showing snapshot" : ""}`, "error");
        if (!state.meta) throw e;
      }
    } else if (snapshotError) {
      throw snapshotError;
    }
  }
  rebuildIndex();
  const columns = state.meta.columns.map((c) => c.id);
  if (!columns.includes(state.focus) || state.meta.columns.find((c) => c.id === state.focus)?.role === "test") {
    const candidates = state.meta.columns.filter((c) => c.role !== "test").map((c) => c.id);
    state.focus = [...candidates].reverse().find((id) => allFeatures().some((f) => f.status?.[id])) ?? candidates[0] ?? columns[0];
  }
}

function rebuildIndex() {
  state.index = new Map();
  for (const entry of state.components) {
    for (const feature of entry.doc.features) state.index.set(feature.id, { entry, feature });
  }
  for (const id of state.selection) if (!state.index.has(id)) state.selection.delete(id);
}

/**
 * Commit a change to one component file. `apply(doc)` mutates a copy of the
 * document and returns it; on a concurrent-edit conflict it is re-run against
 * the latest remote copy, and it should throw when the change no longer applies.
 */
async function commit(entry, apply, message) {
  const { name, branch } = repo();
  const put = (doc, sha) => {
    const errors = validateComponent(doc, state.meta, entry.path.split("/").pop());
    if (errors.length) throw Object.assign(new Error("Validation failed"), { errors });
    const text = dumpComponent(doc, state.meta);
    return gh(`/repos/${name}/contents/${encodePath(entry.path)}`, {
      method: "PUT",
      body: { message, content: utf8ToBase64(text), sha, branch },
    }).then((res) => ({ res, text }));
  };

  let result;
  try {
    result = await put(apply(clone(entry.base)), entry.sha);
  } catch (e) {
    if (!(e.status === 409 || (e.status === 422 && /sha/i.test(e.message)))) throw e;
    const latest = await readFileAt(entry.path, branch);
    result = await put(apply(parseYaml(latest.text), true), latest.sha);
  }
  entry.sha = result.res.content.sha;
  entry.doc = parseYaml(result.text);
  entry.base = clone(entry.doc);
  rebuildIndex();
  return result.res.commit;
}

class ConflictError extends Error {}

/**
 * Commit changes to several component files as ONE commit (Git Data API).
 * Each `apply(latestDoc)` receives the file as it is at the branch head and returns the
 * new document, throwing ConflictError when the change no longer applies. If the branch
 * moves before the ref update (non-fast-forward), everything is redone once from the new head.
 */
async function commitFiles(changes, message) {
  const { name, branch } = repo();
  const ref = encodePath(`heads/${branch}`);
  for (let attempt = 0; ; attempt++) {
    const head = (await gh(`/repos/${name}/git/ref/${ref}`)).object.sha;
    const baseTree = (await gh(`/repos/${name}/git/commits/${head}`)).tree.sha;
    const files = [];
    for (const { entry, apply } of changes) {
      const latest = await readFileAt(entry.path, head);
      const doc = apply(parseYaml(latest.text));
      const errors = validateComponent(doc, state.meta, entry.path.split("/").pop());
      if (errors.length) throw Object.assign(new Error("Validation failed"), { errors });
      const text = dumpComponent(doc, state.meta);
      const blob = await gh(`/repos/${name}/git/blobs`, {
        method: "POST",
        body: { content: utf8ToBase64(text), encoding: "base64" },
      });
      files.push({ entry, text, sha: blob.sha });
    }
    const tree = await gh(`/repos/${name}/git/trees`, {
      method: "POST",
      body: { base_tree: baseTree, tree: files.map((f) => ({ path: f.entry.path, mode: "100644", type: "blob", sha: f.sha })) },
    });
    const created = await gh(`/repos/${name}/git/commits`, {
      method: "POST",
      body: { message, tree: tree.sha, parents: [head] },
    });
    try {
      await gh(`/repos/${name}/git/refs/${ref}`, { method: "PATCH", body: { sha: created.sha, force: false } });
    } catch (e) {
      if (e.status === 422 && attempt === 0) continue;
      if (e.status === 422) throw new Error("Someone else saved at the same moment — press Save again.");
      throw e;
    }
    for (const f of files) {
      f.entry.sha = f.sha;
      f.entry.doc = parseYaml(f.text);
      f.entry.base = clone(f.entry.doc);
    }
    rebuildIndex();
    return { sha: created.sha, html_url: created.html_url };
  }
}

// ---------------------------------------------------------------- routing

function route() {
  const [path, query] = location.hash.replace(/^#/, "").split("?");
  return { parts: (path || "/").split("/").filter(Boolean), params: new URLSearchParams(query ?? "") };
}

function hrefWith(changes) {
  const { parts, params } = route();
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === "") params.delete(key);
    else params.set(key, value);
  }
  const qs = params.toString();
  return `#/${parts.join("/")}${qs ? `?${qs}` : ""}`;
}

function render() {
  const { parts, params } = route();
  document.body.classList.remove("nav-open");
  renderTopbar();
  renderSidebar(parts);
  const content = $("#content");
  document.body.classList.toggle("exported", state.source === "export");
  let view;
  if (parts[0] === "c" && componentEntry(parts[1])) view = viewComponent(parts[1]);
  else if (parts[0] === "search") view = viewSearch(params);
  else view = viewOverview();
  content.innerHTML = versionBanner() + view;
  renderList();
  renderBatchBar();
  renderDrawer(params.get("open"));
}

// ---------------------------------------------------------------- top bar & sidebar

function renderTopbar() {
  document.title = `${state.meta.title}${state.version ? ` ${state.version.name}` : ""}`;
  $("#app-title").textContent = state.meta.title;
  $("#focus-column").innerHTML = columnGroups()
    .map(
      (group) =>
        `<optgroup label="${esc(group.label)}">${group.columns
          .map((c) => `<option value="${c.id}" ${c.id === state.focus ? "selected" : ""}>${esc(columnTitle(c))}</option>`)
          .join("")}</optgroup>`,
    )
    .join("");
  const badge = $("#source-badge");
  const { name, branch } = repo();
  if (state.source === "export") {
    badge.className = "source-badge";
    badge.innerHTML = `Exported ${esc(state.generated.toLocaleString())}`;
    badge.title = "";
  } else if (state.source === "live") {
    badge.className = "source-badge live";
    badge.innerHTML = `<span class="dot"></span>Live`;
    badge.title = `Live data from ${name}@${branch}, loaded ${state.generated.toLocaleString()}`;
  } else {
    badge.className = "source-badge";
    badge.innerHTML = `<span class="dot"></span>Snapshot`;
    badge.title = `Read-only snapshot built by CI on ${state.generated.toLocaleString()}. Sign in to see live data and edit.`;
  }
  renderVersionPicker();
  $("#account-btn").textContent = state.user ? `@${state.user.login}` : state.settings.token ? "Settings" : "Sign in to edit";
  const { parts, params } = route();
  const search = $("#global-search");
  if (document.activeElement !== search) search.value = parts[0] === "search" ? (params.get("q") ?? "") : "";
}

function renderVersionPicker() {
  const picker = $("#version-picker");
  const select = $("#version-select");
  if (state.source === "export") {
    picker.hidden = !state.version;
    select.disabled = true;
    select.innerHTML = state.version ? `<option>${esc(state.version.name)}</option>` : "";
    return;
  }
  const options = [`<option value="">Latest (${esc(repo().branch)})</option>`];
  for (const v of state.versions) {
    options.push(
      `<option value="${esc(v.name)}" ${state.version?.name === v.name ? "selected" : ""}>${esc(v.name)}${v.date ? ` · ${esc(v.date.slice(0, 10))}` : ""}</option>`,
    );
  }
  if (state.source === "live" && state.settings.token) options.push(`<option value="__new">＋ Create version…</option>`);
  select.innerHTML = options.join("");
}

function versionBanner() {
  const v = state.version;
  if (!v) return "";
  const when = v.date ? new Date(v.date).toLocaleString() : "";
  const latest = `${location.pathname}${location.hash}`;
  return `<div class="version-banner">
    <span class="vb-icon">📌</span>
    <div><strong>Version ${esc(v.name)}</strong>${when ? ` · frozen ${esc(when)}` : ""}${v.tagger ? ` by ${esc(v.tagger)}` : ""}
      ${v.message ? `<div class="vb-msg">${esc(v.message)}</div>` : ""}</div>
    ${state.source === "export" ? "" : `<span class="spacer"></span><span class="muted">Read-only</span><a class="btn" href="${esc(latest)}">Back to latest</a>`}
  </div>`;
}

function countBadges(c, column = state.focus, { hideZero = true } = {}) {
  return `<span class="counts">${setOf(column).map((s) =>
    hideZero && !c.values[s.id] ? "" : `<span class="count ${statusInfo(state.meta, columnOf(column), s.id).cls}" title="${esc(s.label)}: ${esc(s.title)}">${c.values[s.id]}</span>`,
  ).join("")}</span>`;
}

// What still needs attention: open (TBD) items first, then items with no status yet.
function openBadge(c, column = state.focus) {
  if (isReq()) {
    return notDone(c) ? `<span class="count tone-open" title="${notDone(c)} not done">${notDone(c)}</span>` : `<span class="done" title="All done">✓</span>`;
  }
  if (c.open) return isDefaultColumn(column)
    ? `<span class="count tbd" title="${c.open} open (TBD)">${c.open}</span>`
    : `<span class="count tone-open" title="${c.open} open">${c.open}</span>`;
  if (c.unset) return `<span class="count unset" title="${c.unset} not set">${c.unset}</span>`;
  return `<span class="done" title="All resolved">✓</span>`;
}

const resolvedOf = (c) => c.resolved;
const totalOf = (c) => c.total;

function renderSidebar(parts) {
  const all = counts(allFeatures());
  const open = isReq() ? notDone(all) : all.open;
  const dflt = isDefaultColumn(state.focus);
  const openStatus = isReq() ? "notdone" : (openIds(state.focus)[0] ?? "unset");
  let html = `
    <a class="nav-home ${parts.length === 0 ? "active" : ""}" href="#/">◎ Overview</a>
    <a class="nav-home ${parts[0] === "search" ? "active" : ""}" href="#/search?status=${openStatus}${keepQuery() ? `&${keepQuery()}` : ""}">◔ ${isReq() ? "Not done" : "Open items"}${dflt ? " (TBD)" : ""} <span class="counts" style="margin-left:auto"><span class="count ${dflt ? "tbd" : "tone-open"}">${open}</span></span></a>`;
  for (const section of state.meta.sections) {
    const entries = state.components.filter((e) => e.doc.id.split(".")[0] === section.id);
    html += `<div class="nav-section"><h4>${esc(section.id)} · ${esc(section.name)}</h4>`;
    for (const entry of entries) {
      const active = parts[0] === "c" && parts[1] === entry.doc.id;
      html += `<a class="nav-item ${active ? "active" : ""}" href="#/c/${entry.doc.id}${keepQuery() ? `?${keepQuery()}` : ""}">
        <span class="nav-id">${esc(entry.doc.id)}</span><span class="nav-name">${esc(entry.doc.name)}</span>${openBadge(counts(entry.doc.features))}</a>`;
    }
    html += `</div>`;
  }
  $("#sidebar").innerHTML = html;
}

// ---------------------------------------------------------------- overview

function donut(c, column, size = 92) {
  const total = totalOf(c) || 1;
  const r = 38;
  const len = 2 * Math.PI * r;
  let offset = 0;
  const arcs = setOf(column)
    .map((s) => {
      const key = s.id;
      const color = TONE_BAR[s.tone];
      const part = (c.values[key] / total) * len;
      const arc = `<circle r="${r}" cx="50" cy="50" fill="none" stroke="${color}" stroke-width="13"
        stroke-dasharray="${part} ${len - part}" stroke-dashoffset="${-offset}" transform="rotate(-90 50 50)"><title>${esc(s.label)}: ${c.values[key]}</title></circle>`;
      offset += part;
      return arc;
    })
    .join("");
  const pct = Math.round((resolvedOf(c) / total) * 100);
  return `<svg width="${size}" height="${size}" viewBox="0 0 100 100">
    <circle r="${r}" cx="50" cy="50" fill="none" stroke="var(--unset)" stroke-width="13"/>${arcs}
    <text x="50" y="52" text-anchor="middle" font-size="19" fill="currentColor" font-weight="500">${pct}%</text>
    <text x="50" y="66" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.6">${isReq() ? "done" : "resolved"}</text></svg>`;
}

function openLine(c, column = state.focus) {
  if (isReq()) {
    if (!notDone(c)) return `<span class="open-line"><span class="done">✓</span> all done</span>`;
    return `<span class="open-line muted">${notDone(c)} not done</span>`;
  }
  if (c.open) return `<span class="open-line"><span class="count ${isDefaultColumn(column) ? "tbd" : "tone-open"}">${c.open}</span> open</span>`;
  if (c.unset === totalOf(c)) return `<span class="open-line muted">not set</span>`;
  if (c.unset) return `<span class="open-line muted">${c.unset} not set</span>`;
  return `<span class="open-line"><span class="done">✓</span> all resolved</span>`;
}

const levelClass = (level) => (level ? ` level-${level}` : "");
const levelMark = (level) => (level && level !== "green" ? "⚠ " : "");

function requirementCards(features) {
  if (!state.meta.fields?.length) return "";
  const cov = coverage(features, state.meta);
  const focus = columnOf(state.focus);
  const rd = riskDone(features, state.meta, focus);
  const covLevel = coverageLevel(cov);
  const rdLevel = riskLevel(rd);
  return `${testColumn(state.meta) ? `<a class="card stat coverage${levelClass(covLevel)}" href="#/search">
        <div class="stat-num">${cov.pct}<small>%</small></div>
        <div class="stat-label">${levelMark(covLevel)}Test coverage</div>
        <div class="stat-sub">YES ${cov.yes} · NO ${cov.no} · TBD ${cov.tbd} · not set ${cov.unset}</div>
        <div class="stat-sub">of ${cov.total} ${word(cov.total)}</div>
      </a>` : ""}
      <a class="card stat risk${levelClass(rdLevel)}" href="#/search?risk=risky">
        <div class="stat-num">${rd.done} / ${rd.total}</div>
        <div class="stat-label">${levelMark(rdLevel)}Risk</div>
        <div class="stat-sub">${rd.pct}% of risky ${word(2)} done on ${esc(focus.name)}</div>
      </a>`;
}

function viewOverview() {
  const features = allFeatures();
  const c = counts(features);
  const focus = state.meta.columns.find((col) => col.id === state.focus);
  const total = totalOf(c) || 1;
  const dflt = isDefaultColumn(focus);
  const req = isReq();
  const listed = req ? included(features, state.meta).length : features.length;

  const platformCards = columnGroups()
    .map((group) => ({ ...group, columns: group.columns.filter((col) => col.role !== "test") }))
    .filter((group) => group.columns.length)
    .map((group) => {
      const platform = state.meta.platforms.find((p) => p.id === group.platform);
      const notes = state.meta.sections
        .map((s) => s.notes?.[group.platform])
        .filter(Boolean)
        .map((n) => `<div>${linkify(n)}</div>`)
        .join("");
      return `<div class="card card-pad">
        <div class="platform-head"><h3>${esc(group.label || "Status")}</h3><span class="muted">${esc(platform?.hardware ?? group.columns[0].hint ?? "")}</span></div>
        <div class="donuts">${group.columns
          .map((col) => {
            const cc = counts(features, col.id);
            return `<div class="donut ${col.id === state.focus ? "focused" : ""}" data-focus="${col.id}" title="Focus on ${esc(columnTitle(col))}">
              ${donut(cc, col)}
              <span class="donut-name">${esc(col.name)}</span>
              ${openLine(cc, col)}
              <span class="hint">${setOf(col).filter((s) => s.resolved).map((s) => `${esc(s.label)} ${cc.values[s.id]}`).join(" · ")}</span>
            </div>`;
          })
          .join("")}</div>
        ${notes ? `<div class="platform-notes">${notes}</div>` : ""}
      </div>`;
    })
    .join("");

  const sections = state.meta.sections
    .map((section) => {
      const entries = state.components.filter((e) => e.doc.id.split(".")[0] === section.id);
      if (!entries.length) return "";
      const rows = entries
        .map((entry) => {
          const cc = counts(entry.doc.features);
          const n = cc.total || 1;
          return `<a class="comp-row ${(req ? notDone(cc) : cc.open) ? "has-open" : ""}" href="#/c/${entry.doc.id}">
            <span class="cid">${esc(entry.doc.id)}</span>
            <span class="cname">${esc(entry.doc.name)}</span>
            <span class="cdesc" title="${esc(entry.doc.description)}">${esc(entry.doc.description ?? "")}</span>
            <span class="bar">${setOf(state.focus).map((s) => `<span class="${statusInfo(state.meta, columnOf(state.focus), s.id).cls}" style="width:${(cc.values[s.id] / n) * 100}%"></span>`).join("")}</span>
            <span class="comp-status"><span class="hint">${resolvedOf(cc)}/${cc.total}</span>${openBadge(cc)}</span>
          </a>`;
        })
        .join("");
      return `<div class="section-block">
        <h2>${esc(section.id)} · ${esc(section.name)}</h2>
        <div class="sub">${esc(section.description ?? "")}</div>
        <div class="card comp-list">${rows}</div>
      </div>`;
    })
    .join("");

  return `
    <div class="page-head">
      <div>
        <h1>${esc(state.meta.title)}</h1>
        <div class="sub">${listed} ${countNoun(state.meta, listed)} in ${state.components.length} components · counts below are for
          <strong>${esc(columnTitle(focus))}</strong></div>
      </div>
      <div class="actions">
        <button class="btn" data-action="export-csv">⤓ Export CSV</button>
        <a class="btn app-only" href="${githubUrl("tree", repo().path)}" target="_blank" rel="noopener">View data on GitHub ↗</a>
      </div>
    </div>
    <div class="grid stats">
      ${req ? `<a class="card stat done" href="#/search">
        <div class="stat-num">${Math.round((resolvedOf(c) / total) * 100)}<small>%</small></div>
        <div class="stat-label">Done</div>
        <div class="stat-sub">${resolvedOf(c)} of ${totalOf(c)} ${word(totalOf(c))}</div>
      </a>` : dflt ? `<a class="card stat open" href="#/search?status=tbd">
        <div class="stat-num">${c.open}</div>
        <div class="stat-label">Open · TBD</div>
        <div class="stat-sub">Not yet verified or still under discussion</div>
      </a>` : `<a class="card stat open" href="#/search?status=${openIds(state.focus)[0] ?? "unset"}">
        <div class="stat-num">${c.open}</div>
        <div class="stat-label">Open</div>
        <div class="stat-sub">Not yet resolved</div>
      </a>`}
      ${req ? "" : `<a class="card stat resolved" href="#/search">
        <div class="stat-num">${Math.round((resolvedOf(c) / total) * 100)}<small>%</small></div>
        <div class="stat-label">Resolved</div>
        <div class="stat-sub">${resolvedOf(c)} of ${totalOf(c)} ${dflt ? "decided (YES or NO)" : "resolved"}</div>
      </a>`}
      ${dflt ? `<a class="card stat supported" href="#/search?status=supported">
        <div class="stat-num">${c.values.supported}</div>
        <div class="stat-label">YES</div>
        <div class="stat-sub">Supported / in scope</div>
      </a>
      <a class="card stat unsupported" href="#/search?status=unsupported">
        <div class="stat-num">${c.values.unsupported}</div>
        <div class="stat-label">NO</div>
        <div class="stat-sub">Not supported / out of scope</div>
      </a>` : setOf(state.focus).map((s) => {
        const lv = req && s.id === "not-supported" ? notSupportedLevel(c.values[s.id]) : null;
        return `<a class="card stat ${statusInfo(state.meta, focus, s.id).cls}${levelClass(lv)}" href="#/search?status=${esc(s.id)}">
        <div class="stat-num">${c.values[s.id]}</div>
        <div class="stat-label">${levelMark(lv)}${esc(s.label)}</div>
        <div class="stat-sub">${esc(s.title)}</div>
      </a>`;
      }).join("")}
      ${isReq() ? `${requirementCards(features)}\n      ` : ""}${c.unset ? `<a class="card stat unset" href="#/search?status=unset"><div class="stat-num">${c.unset}</div><div class="stat-label">Not set</div><div class="stat-sub">No status for this ${req ? "phase" : "milestone"}</div></a>` : ""}
    </div>
    <div class="grid platforms">${platformCards}</div>
    <div class="legend" style="margin:-8px 0 24px">
      ${dflt ? `<span><i style="background:var(--yes-bar)"></i><b>YES</b> resolved – supported / in scope</span>
      <span><i style="background:var(--no-bar)"></i><b>NO</b> resolved – not supported / out of scope</span>
      <span><i style="background:var(--tbd-bar)"></i><b>TBD</b> open – not yet verified / under discussion</span>` : setOf(focus).map((s) => `<span><i style="background:${TONE_BAR[s.tone]}"></i><b>${esc(s.label)}</b> ${req ? (s.resolved ? "done" : "not done") : s.resolved ? "resolved" : "open"} – ${esc(s.title)}</span>`).join("\n      ")}
      <span><i style="background:var(--unset)"></i>Not set</span>
      <span>· Click a chart to change the focus ${req ? "phase" : "milestone"}.</span>
    </div>
    ${sections}`;
}

// ---------------------------------------------------------------- component & search views

function viewComponent(id) {
  const entry = componentEntry(id);
  const doc = entry.doc;
  const section = sectionOf(id);
  const notes = Object.entries(doc.notes ?? {})
    .map(([key, text]) => `<div class="note-card"><header>${esc(noteName(key))}</header><pre>${linkify(text)}</pre></div>`)
    .join("");
  return `
    <div class="crumbs"><a href="#/">Overview</a> / ${esc(section?.name ?? "")}</div>
    <div class="page-head">
      <div>
        <h1>${esc(doc.id)} · ${esc(doc.name)}</h1>
        <div class="sub">${esc(doc.description ?? "")}</div>
      </div>
      <div class="actions">
        <a class="btn" href="${hrefWith({ open: doc.id })}">ⓘ Component info</a>
        ${canEdit() ? `<a class="btn btn-primary" href="${hrefWith({ open: `new:${doc.id}` })}">＋ Add ${word(1)}</a>` : ""}
      </div>
    </div>
    ${notes ? `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr));margin-bottom:12px">${notes}</div>` : ""}
    <div class="toolbar">
      <span id="chips-host"></span>
      <input class="filter-input" id="filter-text" placeholder="Filter this component…" value="${esc(state.filter.text)}">
    </div>
    <div class="card table-wrap" id="list-host"></div>`;
}

function viewSearch(params) {
  state.filter.status = params.get("status") ?? "";
  const q = params.get("q") ?? "";
  return `
    <div class="crumbs"><a href="#/">Overview</a> / Search</div>
    <div class="page-head">
      <div>
        <h1>${q ? `Results for “${esc(q)}”` : state.filter.status ? `${esc(state.filter.status === "notdone" ? "Not done" : statusLabel(state.focus, state.filter.status))} ${word(2)}` : `All ${word(2)}`}</h1>
        <div class="sub">Status filter applies to <strong>${esc(columnTitle(state.meta.columns.find((c) => c.id === state.focus)))}</strong>.</div>
      </div>
    </div>
    <div class="toolbar"><span id="chips-host"></span></div>
    <div class="card table-wrap" id="list-host"></div>`;
}

function matches(entry, feature, text) {
  if (!text) return true;
  const gone = isExcluded(feature);
  const extra = isReq() ? (state.meta.fields ?? []).filter((f) => f.type !== "enum" && (!gone || keptWhenExcluded(f))).map((f) => fieldValue(f, feature)) : [];
  const hay = [feature.id, feature.name, ...(isReq() ? [] : [feature.label]), feature.comment, entry.doc.name, ...(gone ? [] : Object.values(feature.notes ?? {})), ...extra]
    .join("\n")
    .toLowerCase();
  return text
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => hay.includes(word));
}

function renderList() {
  const host = $("#list-host");
  if (!host) return;
  const { parts, params } = route();
  const inSearch = parts[0] === "search";
  const text = inSearch ? (params.get("q") ?? "") : state.filter.text;
  const entries = inSearch ? state.components : [componentEntry(parts[1])];

  const filters = fieldFilters(params);
  const exField = isReq() ? state.meta.exclude_when?.field : null;
  const fieldHit = (f, id, v) => (id === "risk" && v === "risky" ? f.fields?.risk !== "none" : f.fields?.[id] === v);
  // An excluded item is listed only when no filter other than its own exclusion value is active.
  const passes = (f, skip) =>
    Object.entries(filters).every(([id, v]) => id === skip || !v || (isExcluded(f) ? id === exField && fieldHit(f, id, v) : fieldHit(f, id, v)));
  const textAll = entries.flatMap((entry) => entry.doc.features.filter((f) => matches(entry, f, text)).map((f) => ({ entry, f })));
  const textMatched = textAll.filter(({ f }) => passes(f));
  const c = counts(textMatched.map((x) => x.f));
  const chip = (key, label, n) =>
    `<button class="chip ${state.filter.status === key ? "active" : ""}" data-status-filter="${esc(key)}">${esc(label)}<span class="n">${n}</span></button>`;
  const set = setOf(state.focus);
  const notDoneChip = isReq() ? chip("notdone", "Not done", notDone(c)) : "";
  const chipOrder = isDefaultColumn(state.focus) ? ["tbd", "supported", "unsupported"].map((id) => set.find((s) => s.id === id)) : [...set.filter((s) => !s.resolved), ...set.filter((s) => s.resolved)];
  const fieldChips = filterFields()
    .map((fld) => {
      const pool = textAll.filter(({ f }) => passes(f, fld.id) && (!isExcluded(f) || (fld.id === exField && !state.filter.status)));
      const one = (value, label, n) =>
        `<button class="chip ${filters[fld.id] === value ? "active" : ""}" data-field-filter="${esc(fld.id)}" data-value="${esc(value)}">${esc(label)}<span class="n">${n}</span></button>`;
      return `<span class="chips" data-chips="${esc(fld.id)}"><span class="chips-label">${esc(fld.name)}</span>${one("", "All", textAll.filter(({ f }) => passes(f, fld.id) && (!isExcluded(f) || !state.filter.status)).length)}${(fld.values ?? []).map((v) => one(v.id, v.label, pool.filter(({ f }) => f.fields?.[fld.id] === v.id).length)).join("")}${fld.id === "risk" ? one("risky", "Risky", pool.filter(({ f }) => fieldHit(f, "risk", "risky")).length) : ""}</span>`;
    })
    .join("");
  $("#chips-host").innerHTML = `<span class="chips">${chip("", "All", textMatched.length)}${chipOrder.map((s) => chip(s.id, s.label, c.values[s.id])).join("")}${chip("unset", "Not set", c.unset)}${notDoneChip}</span>${fieldChips}`;

  const statusPass = (f) => {
    const want = state.filter.status;
    if (!want) return true;
    if (isExcluded(f)) return false;
    return want === "notdone" ? notDoneIds(state.focus).includes(statusOf(f, state.focus)) : statusOf(f, state.focus) === want;
  };
  const rows = textMatched.filter(({ f }) => statusPass(f));
  if (!rows.length) {
    host.innerHTML = `<div class="empty">No matching ${word(2)}.</div>`;
    return;
  }

  const groups = columnGroups();
  const open = params.get("open");
  const selectable = canEdit();
  state.visibleIds = rows.filter(({ f }) => !isExcluded(f)).map(({ f }) => f.id);
  const selCell = (id) =>
    selectable ? `<td class="sel"><input type="checkbox" data-select="${esc(id)}" ${state.selection.has(id) ? "checked" : ""} aria-label="Select ${esc(id)}"></td>` : "";
  let body = "";
  let lastComponent = null;
  for (const { entry, f } of rows) {
    if (inSearch && entry !== lastComponent) {
      body += `<tr class="comp-heading"><td colspan="${3 + tableFields().length + state.meta.columns.length + (selectable ? 1 : 0)}"><a href="#/c/${entry.doc.id}${keepQuery() ? `?${keepQuery()}` : ""}">${esc(entry.doc.id)} · ${esc(entry.doc.name)}</a></td></tr>`;
      lastComponent = entry;
    }
    if (isExcluded(f)) {
      const exField = state.meta.exclude_when.field;
      body += `<tr data-open="${esc(f.id)}" class="excluded ${open === f.id ? "selected" : ""}">
      ${selectable ? `<td class="sel"></td>` : ""}<td class="fid">${esc(f.id)}</td>
      <td><div class="fname">${esc(f.name)}</div>${f.label && !isReq() ? `<div class="flabel">${esc(f.label)}</div>` : ""}</td>
      ${tableFields().map((fld) => `<td class="ffield">${fld.id === exField ? esc(fieldValue(fld, f)) : ""}</td>`).join("")}<td class="ex-note grp-start" colspan="${state.meta.columns.length + 1}">Out of scope</td>
    </tr>`;
      continue;
    }
    const noteCount = Object.keys(f.notes ?? {}).length;
    body += `<tr data-open="${esc(f.id)}" class="${open === f.id ? "selected" : ""} ${(isReq() ? notDoneIds(state.focus) : openIds(state.focus)).includes(statusOf(f, state.focus)) ? "is-open" : ""} ${state.selection.has(f.id) ? "picked" : ""}">
      ${selCell(f.id)}<td class="fid">${esc(f.id)}</td>
      <td><div class="fname">${esc(f.name)}</div>${f.label && !isReq() ? `<div class="flabel">${esc(f.label)}</div>` : ""}</td>
      ${tableFields().map((fld) => `<td class="ffield ${f.fields?.[fld.id] ? `${esc(fld.id)}-${esc(f.fields[fld.id])}` : ""}">${esc(fieldValue(fld, f))}</td>`).join("")}${groups
        .flatMap((g) => g.columns.map((col, i) => ({ col, first: i === 0 })))
        .map(({ col, first }) => {
          const s = statusOf(f, col.id);
          const cell = pill(col, s);
          return `<td class="st ${first ? "grp-start" : ""} ${col.id === state.focus ? "focus" : ""}">${cell}</td>`;
        })
        .join("")}
      <td class="extra">${featureJira(f)
        .map((k) => `<a class="jira" href="${esc(state.meta.jira_url + k)}" target="_blank" rel="noopener">${k}</a>`)
        .join("")}${noteCount ? `<span class="has-notes" title="${noteCount} note(s)">🗒 ${noteCount}</span>` : ""}</td>
    </tr>`;
  }
  const allPicked = state.visibleIds.length > 0 && state.visibleIds.every((id) => state.selection.has(id));
  const selHead = selectable
    ? `<th class="sel"><input type="checkbox" data-select-all ${allPicked ? "checked" : ""} title="Select all visible rows" aria-label="Select all visible rows"></th>`
    : "";
  host.innerHTML = `<table class="matrix">
    <thead>
      <tr class="groups">${selectable ? "<th></th>" : ""}<th></th><th></th>${tableFields().map(() => "<th></th>").join("")}${groups.map((g) => `<th colspan="${g.columns.length}" class="grp-start">${esc(g.label)}</th>`).join("")}<th></th></tr>
      <tr class="cols">${selHead}<th>ID</th><th>${cap(word(1))}</th>${tableFields().map((fld) => `<th>${esc(fld.name)}</th>`).join("")}${groups
        .flatMap((g) => g.columns.map((col, i) => `<th class="st ${i === 0 ? "grp-start" : ""} ${col.id === state.focus ? "focus" : ""}">${esc(col.name)}</th>`))
        .join("")}<th>Jira · Notes</th></tr>
    </thead>
    <tbody>${body}</tbody></table>`;
  syncSelectAll();
}

/** Header checkbox: checked when every visible row is ticked, indeterminate when some are. */
function syncSelectAll() {
  const header = $("input[data-select-all]");
  if (!header) return;
  const ticked = state.visibleIds.filter((id) => state.selection.has(id)).length;
  header.checked = ticked > 0 && ticked === state.visibleIds.length;
  header.indeterminate = ticked > 0 && ticked < state.visibleIds.length;
}

// ---------------------------------------------------------------- drawer

function renderDrawer(key) {
  const drawer = $("#drawer");
  const open = Boolean(key);
  drawer.classList.toggle("open", open);
  $("#scrim").classList.toggle("open", open);
  drawer.setAttribute("aria-hidden", String(!open));
  if (!open) {
    state.draft = null;
    return;
  }
  if (key.startsWith("new:")) {
    const entry = componentEntry(key.slice(4));
    if (!entry || !canEdit()) return closeDrawer();
    if (state.draft?.key !== key) {
      state.draft = { key, kind: "feature", isNew: true, entry, data: { id: isReq() ? "" : nextFeatureId(entry.doc), name: "", status: {}, ...(isReq() ? { fields: {} } : {}), notes: {} } };
    }
    drawer.innerHTML = featureEditor();
    return;
  }
  const comp = componentEntry(key);
  if (comp) {
    if (state.draft?.key === key) drawer.innerHTML = componentEditor();
    else drawer.innerHTML = componentView(comp);
    return;
  }
  const hit = state.index.get(key);
  if (!hit) {
    drawer.innerHTML = `<div class="drawer-body empty">${cap(word(1))} ${esc(key)} not found.</div>`;
    return;
  }
  drawer.innerHTML = state.draft?.key === key ? featureEditor() : featureView(hit);
}

function closeDrawer() {
  if (state.draft?.dirty && !confirm("Discard unsaved changes?")) return;
  state.draft = null;
  location.hash = hrefWith({ open: null });
}

function drawerHead(entry, title, tags = "") {
  return `<div class="drawer-head">
    <div>
      <div class="crumbs"><a href="#/c/${entry.doc.id}">${esc(entry.doc.id)} · ${esc(entry.doc.name)}</a></div>
      <h2>${esc(title)}</h2>
      <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">${tags}</div>
    </div>
    <button class="icon-btn close" data-action="close-drawer" aria-label="Close">✕</button>
  </div>`;
}

function fieldHtml(fld, item) {
  const v = item.fields?.[fld.id];
  if (fld.type === "list") {
    const links = (Array.isArray(v) ? v : []).map((x) => (fld.link === "jira" && state.meta.jira_url ? `<a class="jira" href="${esc(state.meta.jira_url + x)}" target="_blank" rel="noopener">${esc(x)}</a>` : esc(x)));
    return links.join(" ");
  }
  if (fld.type === "text") return linkify(v ?? "");
  return esc(fieldValue(fld, item));
}

function requirementBody(feature) {
  const all = state.meta.fields ?? [];
  const exField = state.meta.exclude_when?.field;
  const blockFields = (name) => all.filter((f) => f.block === name);
  const row = (f, hideEmpty = false) => {
    const empty = fieldValue(f, feature) === "";
    return hideEmpty && empty ? "" : `<div class="field-label">${esc(f.name)}</div><div class="prose">${empty ? `<span class="muted">—</span>` : fieldHtml(f, feature)}</div>`;
  };
  const section = (id, title, inner) => `<section class="drawer-block" data-block="${id}"><h3 class="block-title">${esc(title)}</h3>${inner}</section>`;
  const reqFields = all.filter((f) => !f.block && (f.show === "detail" || f.id === exField));
  const requirements = section("requirements", "Requirements",
    `${feature.comment ? `<div class="field-label">Description / comment</div><div class="prose">${linkify(feature.comment)}</div>` : ""}${reqFields.map((f) => row(f)).join("")}`);
  if (isExcluded(feature)) return requirements;
  const notes = (...keys) => notesCards(Object.fromEntries(keys.filter((k) => feature.notes?.[k]).map((k) => [k, feature.notes[k]])));
  const phases = state.meta.columns.filter((c) => c.role !== "test");
  const tests = state.meta.columns.filter((c) => c.role === "test");
  const plan = blockFields("test-plan").filter((f) => fieldValue(f, feature) !== "");
  const phasePill = (c) => `<div class="exec-phase"><div class="hint">${esc(c.name)}</div>${pill(c, statusOf(feature, c.id))}</div>`;
  const discovery = section("discovery", "Discovery", blockFields("discovery").map((f) => row(f)).join("") + notes("discovery"));
  const execution = section("execution", "Project execution",
    `<div class="exec-phases">${phases.map(phasePill).join("")}</div>${notes(...phases.map((c) => noteKeyFor(c, state.meta)))}${blockFields("execution").map((f) => row(f)).join("")}`);
  const testPlan = section("test-plan", "Test plan",
    `<div class="exec-phases">${tests.map(phasePill).join("")}</div>${plan.length ? `<div class="test-plan card card-pad">${plan.map((f) => `<div class="tp-row"><div class="hint">${esc(f.name)}</div><div class="prose">${fieldHtml(f, feature)}</div></div>`).join("")}</div>` : ""}${notes(...tests.map((c) => noteKeyFor(c, state.meta)))}`);
  return requirements + discovery + execution + testPlan;
}

function notesCards(notes, ordered = false) {
  let entries = Object.entries(notes ?? {});
  if (ordered) {
    const order = noteOrder(state.meta);
    const rank = (k) => (order.includes(k) ? order.indexOf(k) : order.length);
    entries = entries.sort((a, b) => rank(a[0]) - rank(b[0]));
  }
  const pills = (key) =>
    ordered
      ? state.meta.columns
          .filter((c) => noteKeyFor(c, state.meta) === key)
          .map((c) => `<span class="note-pill"><span class="hint">${esc(c.name)}</span> ${pill(c, statusOf(currentItem, c.id))}</span>`)
          .join("")
      : "";
  return entries
    .map(
      ([key, text], i) => `<div class="note-card">
        <header>${esc(noteName(key))}${pills(key)}<span class="spacer"></span>
          <button class="btn btn-ghost" style="padding:0 6px;font-size:12px" data-copy="${i}">Copy</button></header>
        <pre data-note="${i}">${linkify(text)}</pre></div>`,
    )
    .join("");
}

function editButton(key) {
  if (state.source === "export" || state.version) return "";
  return canEdit()
    ? `<button class="btn btn-primary" data-action="edit" data-key="${esc(key)}">✎ Edit</button>`
    : `<button class="btn" data-action="settings">Sign in to edit</button>`;
}

let currentItem = null;

function featureView({ entry, feature }) {
  currentItem = feature;
  const groups = columnGroups();
  const statusHtml = groups
    .map(
      (g) => `<div class="status-cell ${g.columns.some((c) => c.id === state.focus) ? "focus" : ""}">
        <div class="sc-name">${esc(g.label)}</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap">${g.columns
          .map((c) => `<div style="text-align:center"><div class="hint">${esc(c.name)}</div>${pill(c, statusOf(feature, c.id))}</div>`)
          .join("")}</div></div>`,
    )
    .join("");
  const tags = `<span class="tag">${esc(feature.id)}</span>${feature.label && !isReq() ? `<span class="tag">${esc(feature.label)}</span>` : ""}`;
  return `${drawerHead(entry, feature.name, tags)}
    <div class="drawer-body">
      ${isReq() ? requirementBody(feature) : `<div class="field-label">Status</div>
      <div class="status-grid">${statusHtml}</div>
      ${feature.comment ? `<div class="field-label">Description / comment</div><div class="prose">${linkify(feature.comment)}</div>` : ""}
      <div class="field-label">Notes & evidence</div>
      ${notesCards(feature.notes) || `<div class="muted">No notes yet.</div>`}`}
    </div>
    <div class="drawer-foot">
      ${editButton(feature.id)}
      <span class="spacer"></span>
      <a class="btn btn-ghost app-only" href="https://github.com/${repo().name}/commits/${encodeURIComponent(repo().branch)}/${entry.path}" target="_blank" rel="noopener">History ↗</a>
      <a class="btn btn-ghost app-only" href="${githubUrl("blob", entry.path)}" target="_blank" rel="noopener">YAML ↗</a>
    </div>`;
}

function componentView(entry) {
  const doc = entry.doc;
  return `${drawerHead(entry, doc.name, `<span class="tag">${esc(doc.id)}</span><span class="tag">${doc.features.length} ${countNoun(state.meta, doc.features.length)}</span>`)}
    <div class="drawer-body">
      <div class="field-label">Description</div>
      <div class="prose">${linkify(doc.description ?? "") || `<span class="muted">—</span>`}</div>
      <div class="field-label">Notes</div>
      ${notesCards(doc.notes) || `<div class="muted">No notes yet.</div>`}
    </div>
    <div class="drawer-foot">${editButton(doc.id)}<span class="spacer"></span>
      <a class="btn btn-ghost app-only" href="${githubUrl("blob", entry.path)}" target="_blank" rel="noopener">YAML ↗</a></div>`;
}

function noteKeys() {
  if (isReq()) return noteOrder(state.meta);
  return [...state.meta.platforms.map((p) => p.id), ...(state.meta.note_keys ?? []).map((k) => k.id)];
}

function errorsHtml() {
  const errors = state.draft?.errors;
  return errors?.length ? `<div class="errors">Cannot save:<ul>${errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>` : "";
}

function notesFields(notes) {
  return noteKeys()
    .map(
      (key) => `<div class="form-row"><label>${esc(noteName(key))} notes</label>
        <textarea data-field="notes.${key}" rows="${Math.min(14, Math.max(3, (notes?.[key] ?? "").split("\n").length + 1))}"
          placeholder="Evidence, logs, Jira links…">${esc(notes?.[key] ?? "")}</textarea></div>`,
    )
    .join("");
}

const keptWhenExcluded = (fld) => fld.id === state.meta.exclude_when?.field || (!fld.block && fld.show !== undefined);

function requirementFields(data) {
  const gone = excluded(state.meta, data);
  return (state.meta.fields ?? [])
    .filter((f) => !gone || keptWhenExcluded(f))
    .map((f) => {
      const v = data.fields?.[f.id];
      const attrs = `data-field="${esc(f.id)}" data-req-field`;
      let control;
      if (f.type === "enum") {
        control = `<select ${attrs}><option value=""></option>${(f.values ?? []).map((o) => `<option value="${esc(o.id)}" ${o.id === v ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>`;
      } else if (f.type === "list") {
        control = `<input ${attrs} data-list value="${esc(Array.isArray(v) ? v.join(", ") : "")}" placeholder="Comma-separated">`;
      } else {
        control = `<textarea ${attrs} rows="2">${esc(v ?? "")}</textarea>`;
      }
      return `<div class="form-row"><label>${esc(f.name)}</label>${control}</div>`;
    })
    .join("");
}

function featureEditor() {
  const { entry, data, isNew } = state.draft;
  const seg = (column) => {
    const current = statusOf(data, column.id);
    return `<div class="seg" data-column="${column.id}">${[...setOf(column), { id: "unset", label: "—" }]
      .map((s) => `<button type="button" data-set-status="${esc(s.id)}" title="${esc(s.title ?? "Not set")}" class="${statusInfo(state.meta, column, s.id).cls} ${current === s.id ? "on" : ""}">${esc(s.label)}</button>`)
      .join("")}</div>`;
  };
  const statusHtml = state.meta.columns
    .map((c) => `<div class="status-cell ${c.id === state.focus ? "focus" : ""}"><div class="sc-name">${esc(columnTitle(c))}</div>${seg(c)}</div>`)
    .join("");
  const gone = isReq() && excluded(state.meta, data);
  const idRow = isReq() && isNew ? `<div class="form-row"><label>ID *</label><input data-field-id value="${esc(data.id)}" placeholder="e.g. 5.01"></div>` : "";
  return `${drawerHead(entry, isNew ? `New ${word(1)}` : `Edit ${data.id}`, `<span class="tag">${esc(data.id)}</span>`)}
    <div class="drawer-body">
      ${errorsHtml()}
      ${idRow}<div class="form-row"><label>${cap(word(1))} name *</label><input data-field="name" value="${esc(data.name)}" placeholder="e.g. HDMI hot plug"></div>
      ${isReq() ? "" : `<div class="form-row"><label>Short label</label><input data-field="label" value="${esc(data.label ?? "")}" placeholder="Optional short name"></div>`}
      <div class="form-row"><label>Description / comment</label><textarea data-field="comment" rows="2">${esc(data.comment ?? "")}</textarea></div>
      ${isReq() ? requirementFields(data) : ""}${gone ? `<div class="hint" data-excluded-hint>Out-of-Scope: the other fields are ignored (kept, not deleted) and come back if the scope changes.</div>` : `<div class="field-label">Status</div>
      <div class="status-grid">${statusHtml}</div>
      <div class="field-label">Notes & evidence</div>
      ${notesFields(data.notes)}`}
      <div class="hint">Saving commits directly to <code>${esc(repo().name)}@${esc(repo().branch)}</code>. ${(state.meta.jira_projects ?? []).length ? `Jira keys like ${esc(state.meta.jira_projects[0])}-123 are linked automatically.` : ""}</div>
    </div>
    <div class="drawer-foot">
      <button class="btn btn-primary" data-action="save" ${state.saving ? "disabled" : ""}>${state.saving ? "Saving…" : "Save"}</button>
      <button class="btn" data-action="cancel-edit">Cancel</button>
      <span class="spacer"></span>
      ${isNew ? "" : `<button class="btn btn-danger" data-action="delete">Delete ${word(1)}</button>`}
    </div>`;
}

function componentEditor() {
  const { entry, data } = state.draft;
  return `${drawerHead(entry, `Edit ${data.id}`, `<span class="tag">${esc(data.id)}</span>`)}
    <div class="drawer-body">
      ${errorsHtml()}
      <div class="form-row"><label>Component name *</label><input data-field="name" value="${esc(data.name)}"></div>
      <div class="form-row"><label>Description</label><textarea data-field="description" rows="3">${esc(data.description ?? "")}</textarea></div>
      ${notesFields(data.notes)}
    </div>
    <div class="drawer-foot">
      <button class="btn btn-primary" data-action="save" ${state.saving ? "disabled" : ""}>${state.saving ? "Saving…" : "Save"}</button>
      <button class="btn" data-action="cancel-edit">Cancel</button>
    </div>`;
}

function startEdit(key) {
  if (!canEdit()) return openSettings();
  if (state.saving) {
    toast("Wait until the current save finishes, then edit", "error");
    return;
  }
  const comp = componentEntry(key);
  if (comp) {
    const { features, ...header } = comp.doc;
    state.draft = { key, kind: "component", entry: comp, data: clone(header) };
  } else {
    const hit = state.index.get(key);
    state.draft = { key, kind: "feature", entry: hit.entry, data: clone(hit.feature) };
  }
  renderDrawer(key);
}

async function saveDraft({ remove = false } = {}) {
  const draft = state.draft;
  const { entry, data, kind, isNew } = draft;
  if (kind === "feature" && isReq()) {
    data.id = String(data.id ?? "").trim();
    if (isNew) {
      const taken = state.index.has(data.id) || state.components.some((c) => c.doc.id === data.id);
      if (!data.id || taken) {
        draft.errors = [!data.id ? "ID is required" : `${data.id} already exists`];
        renderDrawer(draft.key);
        return;
      }
    }
  }
  state.saving = true;
  draft.errors = null;
  renderDrawer(draft.key);
  try {
    let commitInfo;
    let savedId = data.id;
    if (kind === "component") {
      const original = (({ features, ...h }) => h)(entry.base);
      commitInfo = await commit(
        entry,
        (doc, rebased) => {
          const { features, ...remoteHeader } = doc;
          if (rebased && JSON.stringify(normalizeComponent({ ...remoteHeader, features: [] }, state.meta)) !== JSON.stringify(normalizeComponent({ ...original, features: [] }, state.meta))) {
            throw new ConflictError("Someone else changed this component's info.");
          }
          return { ...data, features };
        },
        `matrix-table: update ${data.id} ${data.name}`,
      );
    } else if (isNew) {
      commitInfo = await commit(
        entry,
        (doc) => {
          const clash = doc.features.some((f) => f.id === data.id);
          if (clash && isReq()) throw new ConflictError(`${data.id} was added by someone else.`);
          savedId = clash ? nextFeatureId(doc) : data.id;
          doc.features.push({ ...data, id: savedId });
          return doc;
        },
        `matrix-table: add ${data.id} ${data.name}`,
      );
    } else {
      const original = entry.base.features.find((f) => f.id === data.id);
      commitInfo = await commit(
        entry,
        (doc, rebased) => {
          const index = doc.features.findIndex((f) => f.id === data.id);
          if (index < 0) throw new ConflictError(`${data.id} was removed by someone else.`);
          if (rebased && !sameFeature(doc.features[index], original, state.meta)) throw new ConflictError(`Someone else changed ${data.id} meanwhile.`);
          if (remove) doc.features.splice(index, 1);
          else doc.features[index] = data;
          return doc;
        },
        `matrix-table: ${remove ? "delete" : "update"} ${data.id} ${data.name}`,
      );
    }
    state.saving = false;
    state.draft = null;
    toast(`Saved · <a href="${esc(commitInfo.html_url)}" target="_blank" rel="noopener">${esc(commitInfo.sha.slice(0, 7))}</a>`);
    const next = remove ? null : kind === "component" ? data.id : savedId;
    if (location.hash === hrefWith({ open: next })) render();
    else location.hash = hrefWith({ open: next });
  } catch (e) {
    state.saving = false;
    if (e instanceof ConflictError) {
      draft.errors = [`${e.message} Your edit was not saved. Copy your changes, reload, and try again.`];
    } else {
      draft.errors = e.errors ?? [e.message];
    }
    renderDrawer(draft.key);
  }
}

// ---------------------------------------------------------------- batch status change

const batchValues = (column) => [...setOf(column).map((s) => s.id), "unset"];

function localDate() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function batchColumn() {
  const id = state.batch.column && state.meta.columns.some((c) => c.id === state.batch.column) ? state.batch.column : state.focus;
  return state.meta.columns.find((c) => c.id === id);
}

function renderBatchBar() {
  let bar = $("#batch-bar");
  if (!canEdit() || !state.selection.size || !$("#list-host")) {
    bar?.remove();
    return;
  }
  if (!bar) {
    bar = Object.assign(document.createElement("div"), { id: "batch-bar", className: "batch-bar" });
    document.body.append(bar);
  }
  const column = batchColumn();
  const value = state.batch.value;
  const batchNoteKey = noteKeyFor(column, state.meta);
  bar.innerHTML = `
    <strong class="batch-count">${state.selection.size} selected</strong>
    <label class="batch-field">Set <select id="batch-column">${state.meta.columns
      .map((c) => `<option value="${c.id}" ${c.id === column.id ? "selected" : ""}>${esc(columnTitle(c))}</option>`)
      .join("")}</select></label>
    <span class="seg">${batchValues(column).map(
      (v) => `<button type="button" data-batch-value="${esc(v)}" class="${statusInfo(state.meta, column, v).cls} ${v === value ? "on" : ""}" title="${esc(statusTitle(column, v))}">${esc(statusLabel(column, v))}</button>`,
    ).join("")}</span>
    ${batchNoteKey ? `<textarea id="batch-note" rows="1" placeholder="Meeting note (optional) — added to the notes of every changed item">${esc(state.batch.note)}</textarea>` : ""}
    <button class="btn" data-action="batch-clear">Cancel</button>
    <button class="btn btn-primary" data-action="batch-apply" ${value ? "" : "disabled"}>Apply &amp; save</button>`;
}

/** What the batch would do on the loaded data: per component file, and overall. */
function batchPreview() {
  const column = batchColumn();
  const value = state.batch.value;
  const noteKey = noteKeyFor(column, state.meta);
  const options = { noteKey, note: noteKey ? state.batch.note : "", date: localDate(), columnName: column.name, set: setOf(column), applies: (f) => !excluded(state.meta, f) };
  const ids = [...state.selection];
  const missing = ids.filter((id) => !state.index.has(id));
  const files = [];
  for (const entry of state.components) {
    const mine = ids.filter((id) => state.index.get(id)?.entry === entry);
    if (!mine.length) continue;
    const result = applyBatch(entry.doc, mine, column.id, value, { ...options, own: new Set(mine) });
    files.push({ entry, ids: mine, ...result });
  }
  const changed = files.flatMap((f) => f.changed);
  const skipped = files.flatMap((f) => f.skipped);
  const notApplicable = files.flatMap((f) => f.notApplicable);
  return { column, value, options, files, changed, skipped, notApplicable, missing };
}

function batchItemList(p) {
  const rows = (ids, label) => ids.map((id) => {
    const hit = state.index.get(id);
    const old = statusOf(hit.feature, p.column.id);
    return `<li><code>${esc(id)}</code> ${esc(hit.feature.name)}: ${label ? esc(label) : `${esc(statusLabel(p.column, old))} → ${esc(statusLabel(p.column, p.value))}`}</li>`;
  }).join("");
  const skippedLabel = `already ${p.value === "unset" ? "not set" : statusLabel(p.column, p.value)}`;
  return `<details class="batch-items"><summary>Show the ${p.changed.length + p.skipped.length} selected item(s)</summary>
    <ul>${rows(p.changed)}${rows(p.skipped, skippedLabel)}</ul></details>`;
}

function openBatchConfirm() {
  if (state.draft) {
    // Saving the open draft afterwards would overwrite the batch result with its stale copy.
    toast("Save or cancel the item you are editing first, then apply the batch", "error");
    return;
  }
  const p = batchPreview();
  if (!p.changed.length) {
    const already = p.value === "unset" ? "not set" : statusLabel(p.column, p.value);
    const gone = p.missing.length ? `; not found: ${esc(p.missing.join(", "))}` : "";
    const out = p.notApplicable.length ? `; ${p.notApplicable.length} out-of-scope` : "";
    toast(`Nothing to change — ${p.skipped.length} selected item(s) already ${esc(already)}${out}${gone}`);
    return;
  }
  const dialog = $("#dialog");
  const touched = p.files.filter((f) => f.changed.length);
  const sample = p.options.note.trim() ? `<div class="hint" style="margin-top:8px">Note added to each changed item:<br><code>${esc(`${p.options.date} · ${p.column.name}: … → ${statusLabel(p.column, p.value)} — ${p.options.note.trim()}`)}</code></div>` : "";
  dialog.innerHTML = `<form method="dialog" id="batch-confirm">
    <div class="dlg-head"><h2>Apply batch change</h2></div>
    <div class="dlg-body">
      <p style="margin-top:0">Set <strong>${esc(columnTitle(p.column))}</strong> to ${pill(p.column, p.value)} on <strong>${p.changed.length}</strong> item(s).</p>
      <ul class="hint">
        ${p.skipped.length ? `<li>${p.skipped.length} already ${esc(statusLabel(p.column, p.value))} — skipped</li>` : ""}
        ${p.notApplicable.length ? `<li>skipped ${p.notApplicable.length} out-of-scope</li>` : ""}${p.missing.length ? `<li>Not found (removed?): ${esc(p.missing.join(", "))}</li>` : ""}
        <li>One commit touching ${touched.length} file(s): ${touched.map((f) => esc(`${f.entry.doc.id} ${f.entry.doc.name}`)).join(", ")}</li>
      </ul>
      ${batchItemList(p)}
      ${sample}
      <div class="errors" id="batch-error" hidden></div>
    </div>
    <div class="dlg-foot">
      <button class="btn" value="cancel" formnovalidate>Back</button>
      <button class="btn btn-primary" value="confirm" data-action="batch-confirm">Save ${p.changed.length} change(s)</button>
    </div></form>`;
  dialog.showModal();
  let saving = false;
  // While saving, Esc and Back must not close the dialog, or the outcome would never be shown.
  dialog.oncancel = (event) => {
    if (saving) event.preventDefault();
  };
  // Drop the form once the dialog closes so a stale batch can never be submitted later.
  dialog.onclose = () => {
    dialog.onclose = null;
    if ($("#batch-confirm")) dialog.innerHTML = "";
  };
  $("#batch-confirm").addEventListener("submit", async (event) => {
    if (event.submitter?.value !== "confirm") return;
    event.preventDefault();
    const button = event.submitter;
    const back = $('#batch-confirm button[value="cancel"]');
    saving = true;
    state.saving = true;
    button.disabled = true;
    back.disabled = true;
    button.textContent = "Saving…";
    try {
      const info = await saveBatch(p);
      saving = false;
      state.saving = false;
      dialog.oncancel = null;
      dialog.close();
      state.selection.clear();
      state.batch = { column: state.batch.column, value: null, note: "" };
      toast(`Saved ${p.changed.length} change(s) · <a href="${esc(info.html_url)}" target="_blank" rel="noopener">${esc(info.sha.slice(0, 7))}</a>`);
      render();
    } catch (e) {
      saving = false;
      state.saving = false;
      const box = $("#batch-error");
      box.hidden = false;
      box.textContent = e instanceof ConflictError ? `${e.message} Nothing was saved — reload and try again.` : (e.errors ?? [e.message]).join("; ");
      button.disabled = false;
      back.disabled = false;
      button.textContent = `Save ${p.changed.length} change(s)`;
    }
  });
}

/** One commit for the whole batch; each file is re-applied on its latest copy. */
async function saveBatch(p) {
  const touched = p.files.filter((f) => f.changed.length);
  const changes = touched.map(({ entry, ids }) => ({
    entry,
    apply: (latest) => {
      const conflicts = ids.filter((id) => {
        const loaded = entry.base.features.find((f) => f.id === id);
        const now = latest.features.find((f) => f.id === id);
        return !now || !sameFeature(now, loaded, state.meta);
      });
      if (conflicts.length) throw new ConflictError(`Changed or removed by someone else meanwhile: ${conflicts.join(", ")}.`);
      return applyBatch(latest, ids, p.column.id, p.value, { ...p.options, own: new Set(ids) }).doc;
    },
  }));
  const message = batchCommitMessage(columnTitle(p.column), p.value, p.changed.length, { set: p.options.set, nouns: [noun(state.meta, 1), noun(state.meta, 2)] });
  return commitFiles(changes, message);
}

// ---------------------------------------------------------------- settings dialog

function openSettings() {
  const dialog = $("#dialog");
  const { name, branch } = repo();
  dialog.innerHTML = `<form method="dialog" id="settings-form">
    <div class="dlg-head"><h2>Sign in to edit</h2></div>
    <div class="dlg-body">
      <p class="hint" style="margin-top:0">Edits are committed straight to GitHub with your own account. You need a
        <strong>fine-grained personal access token</strong> (one time, ~2 minutes):</p>
      <ol>
        <li>Open <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub → New fine-grained token ↗</a></li>
        <li>Resource owner: <strong>${esc(name.split("/")[0])}</strong> · Repository access: only <strong>${esc(name.split("/")[1])}</strong></li>
        <li>Permissions → Repository → <strong>Contents: Read and write</strong></li>
        <li>Generate, then paste the token below. It is stored only in this browser.</li>
      </ol>
      <div class="form-row"><label>Token</label><input name="token" type="password" autocomplete="off" value="${esc(state.settings.token ?? "")}" placeholder="github_pat_…"></div>
      <details><summary class="hint" style="cursor:pointer">Advanced</summary>
        <div class="form-row" style="margin-top:10px"><label>Repository</label><input name="repo" value="${esc(name)}"></div>
        <div class="form-row"><label>Branch</label><input name="branch" value="${esc(branch)}"></div>
      </details>
      <div class="errors" id="settings-error" hidden></div>
    </div>
    <div class="dlg-foot">
      ${state.settings.token ? `<button class="btn btn-danger" value="signout" style="margin-right:auto">Sign out</button>` : ""}
      <button class="btn" value="cancel">Cancel</button>
      <button class="btn btn-primary" value="save" id="settings-save">Connect</button>
    </div></form>`;
  dialog.showModal();
  $("#settings-form").addEventListener("submit", async (event) => {
    const action = event.submitter?.value;
    if (action === "cancel") return;
    if (action === "signout") {
      state.settings = {};
      state.user = null;
      localStorage.removeItem(`${LS}settings`);
      return reload();
    }
    event.preventDefault();
    const form = new FormData(event.target);
    const meta = state.meta?.repository ?? {};
    const next = {
      token: form.get("token").trim(),
      repo: form.get("repo").trim() !== (meta.name ?? DEFAULT_REPO.name) ? form.get("repo").trim() : undefined,
      branch: form.get("branch").trim() !== (meta.branch ?? DEFAULT_REPO.branch) ? form.get("branch").trim() : undefined,
    };
    const previous = state.settings;
    state.settings = next;
    const button = $("#settings-save");
    button.disabled = true;
    button.textContent = "Checking…";
    try {
      const info = await gh(`/repos/${repo().name}`);
      if (!info.permissions?.push) throw new Error(`This token cannot write to ${repo().name}. Check "Contents: Read and write".`);
      state.user = await gh("/user").catch(() => null);
      localStorage.setItem(`${LS}settings`, JSON.stringify(next));
      dialog.close();
      await reload();
      toast(`Connected${state.user ? ` as @${esc(state.user.login)}` : ""} — editing enabled`);
    } catch (e) {
      state.settings = previous;
      const box = $("#settings-error");
      box.hidden = false;
      box.textContent = e.status === 401 ? "Invalid or expired token." : e.message;
      button.disabled = false;
      button.textContent = "Connect";
    }
  });
}

// ---------------------------------------------------------------- versions (git tags)

function openCreateVersion() {
  const dialog = $("#dialog");
  const { name, branch, tagPrefix } = repo();
  dialog.innerHTML = `<form method="dialog" id="version-form">
    <div class="dlg-head"><h2>Create version</h2></div>
    <div class="dlg-body">
      <p class="hint" style="margin-top:0">Freezes the current data on <code>${esc(branch)}</code> as the git tag
        <code>${esc(tagPrefix)}&lt;version&gt;</code>. Versions are read-only and can be viewed and exported at any time.</p>
      <div class="form-row"><label>Version *</label>
        <input name="version" required pattern="[A-Za-z0-9][A-Za-z0-9._\\-]*" placeholder="e.g. v1.0-beta" autocomplete="off"></div>
      <div class="form-row"><label>Description</label>
        <textarea name="message" rows="3" placeholder="e.g. Delivered to the customer for the Beta milestone"></textarea></div>
      <div class="errors" id="version-error" hidden></div>
    </div>
    <div class="dlg-foot">
      <button class="btn" value="cancel" formnovalidate>Cancel</button>
      <button class="btn btn-primary" value="create" id="version-create">Create version</button>
    </div></form>`;
  dialog.showModal();
  $("#version-form").addEventListener("submit", async (event) => {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const form = new FormData(event.target);
    const version = form.get("version").trim();
    const message = form.get("message").trim() || `Matrix table ${version}`;
    const button = $("#version-create");
    const box = $("#version-error");
    button.disabled = true;
    button.textContent = "Creating…";
    try {
      if (state.versions.some((v) => v.name === version)) throw new Error(`Version “${version}” already exists.`);
      const head = await gh(`/repos/${name}/git/ref/${encodePath(`heads/${branch}`)}`);
      const tag = await gh(`/repos/${name}/git/tags`, {
        method: "POST",
        body: { tag: `${tagPrefix}${version}`, message, object: head.object.sha, type: "commit" },
      });
      await gh(`/repos/${name}/git/refs`, { method: "POST", body: { ref: `refs/tags/${tagPrefix}${version}`, sha: tag.sha } });
      state.versions = [
        { name: version, tag: tag.tag, date: tag.tagger?.date, tagger: tag.tagger?.name, message: tag.message?.trim() },
        ...state.versions,
      ];
      renderVersionPicker();
      dialog.close();
      toast(`Version <strong>${esc(version)}</strong> created · <a href="?v=${encodeURIComponent(version)}${esc(location.hash)}">View</a>`);
    } catch (e) {
      box.hidden = false;
      box.textContent = e.message;
      button.disabled = false;
      button.textContent = "Create version";
    }
  });
}

function switchVersion(value) {
  if (value === "__new") {
    renderVersionPicker();
    return openCreateVersion();
  }
  if (state.draft?.dirty && !confirm("Discard unsaved changes?")) return renderVersionPicker();
  const url = new URL(location.href);
  if (value) url.searchParams.set("v", value);
  else url.searchParams.delete("v");
  location.href = url.toString();
}

// ---------------------------------------------------------------- standalone HTML export

async function exportHtml() {
  const button = $('[data-action="export-html"]');
  button.disabled = true;
  try {
    const files = ["index.html", "style.css", "app.js", "model.js", "template.js", "vendor/js-yaml.mjs"];
    const [html, css, appJs, modelJs, templateJs, yamlJs] = await Promise.all(
      files.map(async (file) => {
        const res = await fetch(file, { cache: "no-store" });
        if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
        return res.text();
      }),
    );
    // Inline the ES modules as data: URLs so the report works from file:// without a server.
    // A data: module cannot resolve relative imports, so every "./x.js" must be replaced;
    // app.js and model.js share one template.js URL so the browser loads a single instance.
    const asModule = (js) => `data:text/javascript;base64,${utf8ToBase64(js)}`;
    const template = JSON.stringify(asModule(templateJs));
    const model = modelJs.replace('"./vendor/js-yaml.mjs"', () => JSON.stringify(asModule(yamlJs))).replace('"./template.js"', () => template);
    const app = appJs.replace('"./model.js"', () => JSON.stringify(asModule(model))).replace('"./template.js"', () => template);
    for (const [name, js] of [["template.js", templateJs], ["model.js", model], ["app.js", app]]) {
      if (/\bfrom\s+["']\.\.?\//.test(js)) throw new Error(`${name} still has a relative import; cannot export`);
    }
    const payload = {
      generated: new Date().toISOString(),
      version: state.version,
      meta: state.meta,
      components: state.components.map(({ path, doc }) => ({ path, doc })),
    };
    const json = JSON.stringify(payload).replace(/</g, "\\u003c");
    const title = `${state.meta.title}${state.version ? ` ${state.version.name}` : ""}`;
    const out = html
      .replace(/<title>.*<\/title>/, () => `<title>${esc(title)}</title>`)
      .replace('<link rel="stylesheet" href="style.css">', () => `<style>\n${css}\n</style>`)
      .replace(
        '<script type="module" src="app.js"></script>',
        () => `<script id="embedded-data" type="application/json">${json}</script>\n  <script type="module">import ${JSON.stringify(asModule(app))};</script>`,
      );
    if (!out.includes('id="embedded-data"') || !out.includes("<style>")) throw new Error("index.html template changed; cannot export");

    const slug = state.meta.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const stamp = payload.generated.slice(0, 10).replace(/-/g, "");
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(new Blob([out], { type: "text/html" })),
      download: `${slug}_${state.version?.name ?? "latest"}_${stamp}.html`,
    });
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Exported ${esc(a.download)}`);
  } catch (e) {
    toast(`Export failed: ${esc(e.message)}`, "error");
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- CSV export

function exportCsv() {
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const keys = noteKeys();
  const extra = isReq() ? (state.meta.fields ?? []) : [];
  const header = ["ID", "Section", "Component", cap(word(1)), ...(isReq() ? [] : ["Label"]), "Comment", ...extra.map((f) => f.name), ...state.meta.columns.map(columnTitle), ...keys.map((k) => `${noteName(k)} notes`)];
  const lines = [header.map(cell).join(",")];
  for (const entry of state.components) {
    for (const f of entry.doc.features) {
      lines.push(
        [
          f.id,
          sectionOf(entry.doc.id)?.name,
          entry.doc.name,
          f.name,
          ...(isReq() ? [] : [f.label]),
          f.comment,
          ...extra.map((fld) => (isExcluded(f) && !keptWhenExcluded(fld) ? "" : fieldValue(fld, f))),
          ...state.meta.columns.map((c) => (!isExcluded(f) && f.status?.[c.id] ? statusLabel(c, f.status[c.id]) : "")),
          ...keys.map((k) => (isExcluded(f) ? "" : f.notes?.[k])),
        ]
          .map(cell)
          .join(","),
      );
    }
  }
  const blob = new Blob([`\ufeff${lines.join("\r\n")}`], { type: "text/csv" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "matrix-table.csv" });
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------------------------------------------------------- events

document.addEventListener("click", (event) => {
  const target = event.target;
  const action = target.closest("[data-action]")?.dataset.action;
  if (action === "close-drawer") return closeDrawer();

  const pick = target.closest("input[data-select]");
  if (pick) {
    if (pick.checked) state.selection.add(pick.dataset.select);
    else state.selection.delete(pick.dataset.select);
    pick.closest("tr")?.classList.toggle("picked", pick.checked);
    syncSelectAll();
    renderBatchBar();
    return;
  }
  if (target.closest("input[data-select-all]")) {
    const all = state.visibleIds.every((id) => state.selection.has(id));
    for (const id of state.visibleIds) all ? state.selection.delete(id) : state.selection.add(id);
    for (const box of document.querySelectorAll("input[data-select]")) {
      box.checked = state.selection.has(box.dataset.select);
      box.closest("tr")?.classList.toggle("picked", box.checked);
    }
    syncSelectAll();
    renderBatchBar();
    return;
  }
  const batchValue = target.closest("[data-batch-value]");
  if (batchValue) {
    state.batch.value = batchValue.dataset.batchValue;
    renderBatchBar();
    return;
  }
  if (action === "batch-clear") {
    state.selection.clear();
    state.batch = { column: state.batch.column, value: null, note: "" };
    for (const box of document.querySelectorAll("input[data-select]")) {
      box.checked = false;
      box.closest("tr")?.classList.remove("picked");
    }
    syncSelectAll();
    renderBatchBar();
    return;
  }
  if (action === "batch-apply") return openBatchConfirm();
  if (action === "settings") return openSettings();
  if (action === "refresh") return reload();
  if (action === "toggle-nav") return document.body.classList.toggle("nav-open");
  if (action === "export-csv") return exportCsv();
  if (action === "export-html") return exportHtml();
  if (action === "edit") return startEdit(target.closest("[data-key]").dataset.key);
  if (action === "save") return saveDraft();
  if (action === "delete") {
    if (confirm(`Delete ${state.draft.data.id} “${state.draft.data.name}”? This commits immediately.`)) saveDraft({ remove: true });
    return;
  }
  if (action === "cancel-edit") {
    if (state.draft?.dirty && !confirm("Discard unsaved changes?")) return;
    const { key, isNew } = state.draft;
    state.draft = null;
    if (isNew) location.hash = hrefWith({ open: null });
    else renderDrawer(key);
    return;
  }

  const focus = target.closest("[data-focus]");
  if (focus) return setFocus(focus.dataset.focus);

  const fieldFilter = target.closest("[data-field-filter]");
  if (fieldFilter) {
    location.hash = hrefWith({ [fieldFilter.dataset.fieldFilter]: fieldFilter.dataset.value });
    return;
  }

  const statusFilter = target.closest("[data-status-filter]");
  if (statusFilter) {
    state.filter.status = statusFilter.dataset.statusFilter;
    if (route().parts[0] === "search") location.hash = hrefWith({ status: state.filter.status });
    else renderList();
    return;
  }

  const setStatus = target.closest("[data-set-status]");
  if (setStatus && state.draft) {
    const column = setStatus.closest("[data-column]").dataset.column;
    state.draft.data.status = { ...state.draft.data.status, [column]: setStatus.dataset.setStatus === "unset" ? undefined : setStatus.dataset.setStatus };
    state.draft.dirty = true;
    for (const button of setStatus.parentElement.children) button.classList.toggle("on", button === setStatus);
    return;
  }

  const copy = target.closest("[data-copy]");
  if (copy) {
    const text = copy.closest(".note-card").querySelector("pre").innerText;
    navigator.clipboard.writeText(text).then(() => toast("Copied to clipboard"));
    return;
  }

  const row = target.closest("tr[data-open]");
  if (row && !target.closest("a") && !target.closest("td.sel")) location.hash = hrefWith({ open: row.dataset.open });
});

function onDraftInput(event) {
  const field = event.target.dataset?.field;
  if (field && state.draft) {
    const value = event.target.value;
    if (event.target.dataset.reqField !== undefined) {
      const fields = { ...state.draft.data.fields };
      const parsed = event.target.dataset.list !== undefined ? value.split(",").map((x) => x.trim()).filter(Boolean) : value;
      if (parsed === "" || (Array.isArray(parsed) && !parsed.length)) delete fields[field];
      else fields[field] = parsed;
      state.draft.data.fields = fields;
      state.draft.dirty = true;
      if (event.target.tagName === "SELECT") renderDrawer(state.draft.key);
      return;
    }
    if (field.startsWith("notes.")) state.draft.data.notes = { ...state.draft.data.notes, [field.slice(6)]: value };
    else state.draft.data[field] = value;
    state.draft.dirty = true;
    return;
  }
  if (event.target.dataset?.fieldId !== undefined && state.draft) {
    state.draft.data.id = event.target.value;
    state.draft.dirty = true;
    return;
  }
  if (event.target.id === "batch-note") {
    state.batch.note = event.target.value;
    return;
  }
  if (event.target.id === "filter-text") {
    state.filter.text = event.target.value;
    renderList();
  }
  if (event.target.id === "global-search") {
    const q = event.target.value;
    const hash = q ? `#/search?q=${encodeURIComponent(q)}` : "#/";
    history.replaceState(null, "", hash);
    state.filter.status = "";
    render();
  }
}
document.addEventListener("input", onDraftInput);

document.addEventListener("change", (event) => {
  if (event.target.tagName === "SELECT" && event.target.dataset.reqField !== undefined && state.draft) onDraftInput(event);
});
$("#focus-column").addEventListener("change", (event) => setFocus(event.target.value));
document.addEventListener("change", (event) => {
  if (event.target.id === "batch-column") {
    state.batch.column = event.target.value;
    if (!batchValues(batchColumn()).includes(state.batch.value)) state.batch.value = null;
    renderBatchBar();
  }
});
$("#version-select").addEventListener("change", (event) => switchVersion(event.target.value));

function setFocus(column) {
  state.focus = column;
  localStorage.setItem(`${LS}focus`, column);
  render();
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && route().params.get("open") && !$("#dialog").open) closeDrawer();
  if (event.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    event.preventDefault();
    $("#global-search").focus();
  }
});

let lastPath = null;
window.addEventListener("hashchange", () => {
  const path = route().parts.join("/");
  if (path !== lastPath) {
    if (!path.startsWith("search")) state.filter = { status: "", text: "" };
    lastPath = path;
  }
  render();
});
window.addEventListener("beforeunload", (event) => {
  if (state.draft?.dirty) event.preventDefault();
});

async function reload() {
  try {
    await load();
    if (state.settings.token && !state.user && state.source === "live") state.user = await gh("/user").catch(() => null);
    lastPath = route().parts.join("/");
    render();
  } catch (e) {
    $("#content").innerHTML = `<div class="card card-pad" style="max-width:640px;margin:40px auto">
      <h3>Could not load the matrix table</h3><p class="muted">${esc(e.message)}</p>
      <p>Sign in with a GitHub token to load live data from the repository.</p>
      <button class="btn btn-primary" data-action="settings">Sign in</button></div>`;
  }
}

reload();
