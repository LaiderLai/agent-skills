// Pure helpers for data templates (feature matrix / requirement matrix), shared by the
// web app (browser) and tools (Node).

// YES / NO are resolved decisions (done); TBD is open and needs attention.
export const STATUSES = [
  { id: "supported", label: "YES", resolved: true, title: "Resolved – supported / in scope" },
  { id: "unsupported", label: "NO", resolved: true, title: "Resolved – not supported / out of scope" },
  { id: "tbd", label: "TBD", resolved: false, title: "Open – not yet verified, still under discussion" },
];
export const STATUS_IDS = STATUSES.map((s) => s.id);

export const TONES = ["yes", "no", "open", "neutral", "info", "warn"];
const DEFAULT_TONES = { supported: "yes", unsupported: "no", tbd: "open" };
const UNSET = { label: "—", title: "Not set", cls: "unset" };

export const isRequirement = (meta) => meta?.template === "requirement-matrix";

export function noun(meta, n) {
  const [one, many] = meta?.noun ?? ["feature", "features"];
  return n === 1 ? one : many;
}

/** Noun after a count: feature matrices keep the historical always-plural "features". */
export const countNoun = (meta, n) => (isRequirement(meta) ? noun(meta, n) : "features");

const usesDefault = (column) => !column?.status_set || column.status_set === "default";

export function statusSet(meta, column) {
  if (usesDefault(column)) return STATUSES.map((s) => ({ ...s, tone: DEFAULT_TONES[s.id] }));
  return meta.status_sets?.[column.status_set] ?? [];
}

export function statusInfo(meta, column, value) {
  if (!value || value === "unset") return { ...UNSET };
  const s = statusSet(meta, column).find((x) => x.id === value);
  if (!s) return { label: value, title: value, cls: "unset" };
  return { label: s.label, title: s.title, cls: usesDefault(column) ? s.id : `tone-${s.tone}` };
}

export function tally(features, meta, column) {
  const set = statusSet(meta, column);
  const values = Object.fromEntries(set.map((s) => [s.id, 0]));
  let unset = 0;
  for (const f of features) {
    const v = f.status?.[column.id];
    if (v && v in values) values[v]++;
    else unset++;
  }
  const resolved = set.filter((s) => s.resolved).reduce((n, s) => n + values[s.id], 0);
  const open = set.filter((s) => !s.resolved).reduce((n, s) => n + values[s.id], 0);
  return { values, unset, resolved, open, total: features.length };
}

export const noteKeyFor = (column, meta) => (isRequirement(meta) ? column.note_key : column.platform) ?? null;

export function noteOrder(meta) {
  if (isRequirement(meta)) return (meta.note_keys ?? []).map((k) => k.id);
  return (meta.platforms ?? []).map((p) => p.id);
}

export const excluded = (meta, item) => {
  const w = meta?.exclude_when;
  return !!w && item.fields?.[w.field] === w.equals;
};

export const included = (features, meta) => features.filter((f) => !excluded(meta, f));

export function done(features, meta, column) {
  const t = tally(included(features, meta), meta, column);
  return { done: t.resolved, total: t.total, pct: t.total ? Math.round((t.resolved / t.total) * 100) : 0 };
}

export const risky = (features, meta) => included(features, meta).filter((f) => f.fields?.risk !== "none");

export function riskDone(features, meta, column) {
  const items = risky(features, meta);
  const t = tally(items, meta, column);
  return { done: t.resolved, total: t.total, pct: t.total ? Math.round((t.resolved / t.total) * 100) : 0, items };
}

export const testColumn = (meta) => meta.columns?.find((c) => c.role === "test");

export function coverage(features, meta) {
  const col = testColumn(meta);
  const out = { total: 0, yes: 0, no: 0, tbd: 0, unset: 0, pct: 0 };
  if (!col) return out;
  for (const f of included(features, meta)) {
    out.total++;
    const v = f.status?.[col.id];
    if (v === "supported") out.yes++;
    else if (v === "unsupported") out.no++;
    else if (v === "tbd") out.tbd++;
    else out.unset++;
  }
  out.pct = out.total ? Math.round((out.yes / out.total) * 100) : 0;
  return out;
}

export function coverageLevel(cov) {
  if (!cov.total) return null;
  return cov.pct >= 100 ? "green" : cov.pct >= 80 ? "yellow" : cov.pct >= 50 ? "orange" : "red";
}

export function riskLevel(rd) {
  if (!rd.total) return "green";
  return rd.done >= rd.total ? "green" : rd.done === 0 ? "red" : "orange";
}

export const notSupportedLevel = (n) => (n > 0 ? "red" : null);

const REQ_ONLY_META = ["fields", "status_sets", "note_keys", "noun", "exclude_when"];
const REQ_ONLY_COLUMN = ["status_set", "note_key", "role", "applies_when"];

/** Returns a list of human readable errors for the template parts of _meta.yaml. */
export function validateMeta(meta) {
  const errors = [];
  const err = (msg) => errors.push(`_meta.yaml: ${msg}`);
  const unique = (ids, what) => {
    const seen = new Set();
    for (const id of ids) {
      if (seen.has(id)) err(`duplicate ${what} "${id}"`);
      seen.add(id);
    }
  };
  if (!meta || typeof meta !== "object") return ["_meta.yaml: not a YAML mapping"];
  if (meta.template !== undefined && !["feature-matrix", "requirement-matrix"].includes(meta.template)) {
    err(`template "${meta.template}" must be feature-matrix or requirement-matrix`);
  }
  const isMap = (x) => x && typeof x === "object" && !Array.isArray(x);
  const list = (key) => {
    const v = meta[key] ?? [];
    if (!Array.isArray(v)) {
      err(`"${key}" must be a list`);
      return [];
    }
    return v;
  };
  const mappings = (key, what) =>
    list(key).filter((x, n) => {
      if (isMap(x)) return true;
      err(`${what} ${n + 1} must be a mapping`);
      return false;
    });
  const columns = mappings("columns", "column");
  if (!isRequirement(meta)) {
    for (const key of REQ_ONLY_META) if (key in meta) err(`"${key}" requires template: requirement-matrix`);
    for (const c of columns) {
      for (const key of REQ_ONLY_COLUMN) if (key in c) err(`column "${c.id}": "${key}" requires template: requirement-matrix`);
    }
    return errors;
  }
  const sets = isMap(meta.status_sets) ? meta.status_sets : {};
  if (meta.status_sets !== undefined && !isMap(meta.status_sets)) err('"status_sets" must be a mapping');
  if ("default" in sets) err('status set "default" is reserved');
  for (const [name, rawSet] of Object.entries(sets)) {
    if (!Array.isArray(rawSet)) {
      err(`status set "${name}" must be a list`);
      continue;
    }
    const set = rawSet.filter((s) => {
      if (isMap(s)) return true;
      err(`status set "${name}": entries must be mappings`);
      return false;
    });
    for (const s of set) {
      if (!s.id || !s.label) err(`status "${s.id ?? ""}" in set "${name}" needs id and label`);
      if (typeof s.resolved !== "boolean") err(`status "${s.id ?? ""}" in set "${name}": resolved must be true or false`);
    }
    unique(set.map((s) => s.id), `status id in set "${name}"`);
    for (const s of set) if (!TONES.includes(s.tone)) err(`status set "${name}": tone "${s.tone}" of "${s.id}" must be one of ${TONES.join(", ")}`);
  }
  for (const c of columns) if ("applies_when" in c) err(`column "${c.id}": applies_when is obsolete, use exclude_when`);
  const fields = mappings("fields", "field");
  unique(fields.map((f) => f.id), "field id");
  for (const f of fields) {
    if (!["enum", "text", "list"].includes(f.type)) err(`field "${f.id}": type "${f.type}" must be enum, text or list`);
    if (f.link !== undefined && f.link !== "jira") err(`field "${f.id}": link "${f.link}" must be jira`);
    if (f.type === "enum") {
      const values = (Array.isArray(f.values) ? f.values : []).filter((v) => {
        if (isMap(v)) return true;
        err(`field "${f.id}": values must be mappings`);
        return false;
      });
      unique(values.map((v) => v.id), `value id in field "${f.id}"`);
      for (const v of values) if (v.tone !== undefined && !TONES.includes(v.tone)) err(`field "${f.id}": tone "${v.tone}" must be one of ${TONES.join(", ")}`);
    }
  }
  const keys = mappings("note_keys", "note key").map((k) => k.id);
  unique(keys, "note key");
  const reserved = ["general", ...mappings("platforms", "platform").map((p) => p.id)];
  for (const k of keys) if (reserved.includes(k)) err(`note key "${k}" is reserved ("general" is no longer supported; platform ids are reserved too)`);
  for (const c of columns) {
    if (!c.note_key || !keys.includes(c.note_key)) err(`column "${c.id}": note_key "${c.note_key ?? ""}" must be one of the note_keys`);
    if (c.status_set && c.status_set !== "default" && !(c.status_set in sets)) err(`column "${c.id}": status_set "${c.status_set}" is not defined`);
  }
  const w = meta.exclude_when;
  if (w !== undefined && w !== null) {
    if (!isMap(w)) err("exclude_when must be a mapping");
    else {
      const f = fields.find((x) => x.id === w.field);
      if (!f || f.type !== "enum") err(`exclude_when field "${w.field}" must be an enum field`);
      else if (!(Array.isArray(f.values) ? f.values : []).some((v) => v?.id === w.equals)) err(`exclude_when value "${w.equals}" is not a value of "${w.field}"`);
    }
  }
  return errors;
}
