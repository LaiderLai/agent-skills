// Shared data model for the matrix table: used by the web editor (browser)
// and by tools/build.mjs (Node, CI) so both write byte-identical YAML.
import { load, dump } from "./vendor/js-yaml.mjs";

import { STATUSES, STATUS_IDS, noteOrder, statusSet, isRequirement } from "./template.js";

export { STATUSES, STATUS_IDS };

const COMPONENT_KEYS = ["id", "name", "description", "notes", "features"];
const FEATURE_KEYS = ["id", "name", "label", "comment", "status", "notes"];
const featureKeys = (meta) => (isRequirement(meta) ? ["id", "name", "comment", "status", "fields", "notes"] : FEATURE_KEYS);
const REQ_ID = /^[0-9A-Za-z][0-9A-Za-z._-]*$/;

export function cleanText(value) {
  if (value === undefined || value === null) return "";
  return String(value)
    .replace(/\r\n?/g, "\n")
    .replace(/\t/g, "    ")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function orderedNotes(notes, meta) {
  if (!notes || typeof notes !== "object") return undefined;
  const order = noteOrder(meta ?? {});
  const keys = [...order.filter((k) => k in notes), ...Object.keys(notes).filter((k) => !order.includes(k))];
  const out = {};
  for (const key of keys) {
    const text = cleanText(notes[key]);
    if (text) out[key] = text;
  }
  return Object.keys(out).length ? out : undefined;
}

function orderedStatus(status, meta) {
  if (!status || typeof status !== "object") return undefined;
  const order = (meta?.columns ?? []).map((c) => c.id);
  const keys = [...order.filter((k) => k in status), ...Object.keys(status).filter((k) => !order.includes(k))];
  const out = {};
  for (const key of keys) {
    if (status[key]) out[key] = status[key];
  }
  return Object.keys(out).length ? out : undefined;
}

function orderedFields(fields, meta) {
  if (!fields || typeof fields !== "object" || Array.isArray(fields)) return undefined;
  const defs = meta?.fields ?? [];
  const order = defs.map((f) => f.id);
  const keys = [...order.filter((k) => k in fields), ...Object.keys(fields).filter((k) => !order.includes(k))];
  const out = {};
  for (const key of keys) {
    const value = fields[key];
    if (defs.find((f) => f.id === key)?.type === "list" || Array.isArray(value)) {
      const list = (Array.isArray(value) ? value : [value]).map((v) => cleanText(v)).filter(Boolean);
      if (list.length) out[key] = list;
    } else {
      const text = cleanText(value);
      if (text) out[key] = text;
    }
  }
  return Object.keys(out).length ? out : undefined;
}

export function normalizeFeature(feature, meta) {
  const req = isRequirement(meta);
  const out = {
    id: cleanText(feature.id),
    name: cleanText(feature.name),
    ...(req ? {} : { label: cleanText(feature.label) }),
    comment: cleanText(feature.comment),
    status: orderedStatus(feature.status, meta),
    ...(req ? { fields: orderedFields(feature.fields, meta) } : {}),
    notes: orderedNotes(feature.notes, meta),
  };
  if (!req && out.label === out.name) out.label = "";
  for (const key of Object.keys(feature)) {
    if (!featureKeys(meta).includes(key)) out[key] = feature[key];
  }
  return prune(out);
}

export function normalizeComponent(component, meta) {
  const out = {
    id: cleanText(component.id),
    name: cleanText(component.name),
    description: cleanText(component.description),
    notes: orderedNotes(component.notes, meta),
    features: (component.features ?? []).map((f) => normalizeFeature(f, meta)),
  };
  for (const key of Object.keys(component)) {
    if (!COMPONENT_KEYS.includes(key)) out[key] = component[key];
  }
  return prune(out, ["features"]);
}

function prune(obj, keep = []) {
  for (const [key, value] of Object.entries(obj)) {
    if (keep.includes(key)) continue;
    if (value === undefined || value === "") delete obj[key];
  }
  return obj;
}

export function parseYaml(text) {
  return load(text);
}

export function dumpComponent(component, meta) {
  return dump(normalizeComponent(component, meta), {
    indent: 2,
    lineWidth: -1,
    noRefs: true,
    quotingType: '"',
  });
}

/** Returns a list of human readable errors; empty when valid. */
export function validateComponent(component, meta, label = component?.id ?? "?") {
  const errors = [];
  const err = (msg) => errors.push(`${label}: ${msg}`);
  if (!component || typeof component !== "object") return [`${label}: not a YAML mapping`];

  const sectionIds = (meta.sections ?? []).map((s) => s.id);
  const columnIds = (meta.columns ?? []).map((c) => c.id);
  const req = isRequirement(meta);
  const noteKeys = noteOrder(meta);

  for (const key of Object.keys(component)) {
    if (!COMPONENT_KEYS.includes(key)) err(`unknown key "${key}"`);
  }
  if (!/^[A-Z]\.\d+$/.test(component.id ?? "")) err(`id "${component.id}" must look like "A.1"`);
  else if (!sectionIds.includes(component.id.split(".")[0])) err(`section "${component.id.split(".")[0]}" is not defined in _meta.yaml`);
  if (!cleanText(component.name)) err("name is required");
  checkNotes(component.notes, noteKeys, err);
  if (!Array.isArray(component.features)) {
    err("features must be a list");
    return errors;
  }

  const seen = new Set();
  component.features.forEach((feature, index) => {
    const where = `feature #${index + 1}${feature?.id ? ` (${feature.id})` : ""}`;
    const ferr = (msg) => err(`${where}: ${msg}`);
    if (!feature || typeof feature !== "object") return ferr("not a mapping");
    for (const key of Object.keys(feature)) {
      if (!featureKeys(meta).includes(key)) ferr(`unknown key "${key}"`);
    }
    if (req) {
      if (typeof feature.id !== "string") ferr('id must be a quoted string, e.g. "2.10"');
      else if (!REQ_ID.test(feature.id)) ferr(`id "${feature.id}" must match ${REQ_ID}`);
      else if (seen.has(feature.id)) ferr("duplicate id");
    } else if (!new RegExp(`^${escapeRe(component.id)}\\.\\d+$`).test(feature.id ?? "")) {
      ferr(`id must look like "${component.id}.<n>"`);
    } else if (seen.has(feature.id)) {
      ferr("duplicate id");
    }
    seen.add(feature.id);
    if (!cleanText(feature.name)) ferr("name is required");
    if (feature.status !== undefined) {
      if (typeof feature.status !== "object" || Array.isArray(feature.status)) ferr("status must be a mapping");
      else {
        for (const [column, value] of Object.entries(feature.status)) {
          if (!columnIds.includes(column)) ferr(`status column "${column}" is not defined in _meta.yaml`);
          const col = (meta.columns ?? []).find((c) => c.id === column);
          const ids = req && col ? statusSet(meta, col).map((s) => s.id) : STATUS_IDS;
          if (value && !ids.includes(value)) ferr(`status "${column}: ${value}" must be one of ${ids.join(", ")}`);
        }
      }
    }
    if (req && feature.fields !== undefined) checkFields(feature.fields, meta, ferr);
    checkNotes(feature.notes, noteKeys, ferr);
  });
  return errors;
}

function checkFields(fields, meta, err) {
  if (typeof fields !== "object" || fields === null || Array.isArray(fields)) return err("fields must be a mapping");
  const defs = meta.fields ?? [];
  for (const [key, value] of Object.entries(fields)) {
    const def = defs.find((f) => f.id === key);
    if (!def) {
      err(`fields key "${key}" is not defined in _meta.yaml`);
      continue;
    }
    if (def.type === "list") {
      if (!Array.isArray(value) || value.some((v) => typeof v !== "string")) err(`fields "${key}" must be a list of text`);
    } else if (typeof value !== "string") err(`fields "${key}" must be text`);
    else if (def.type === "enum") {
      const ids = (def.values ?? []).map((v) => v.id);
      if (value && !ids.includes(value)) err(`fields "${key}: ${value}" must be one of ${ids.join(", ")}`);
    }
  }
}

function checkNotes(notes, allowed, err) {
  if (notes === undefined) return;
  if (typeof notes !== "object" || Array.isArray(notes)) return err("notes must be a mapping");
  for (const [key, value] of Object.entries(notes)) {
    if (!allowed.includes(key)) err(`notes key "${key}" must be one of ${allowed.join(", ")} (a "general" note cannot be kept: re-import the source or move the text to one of these keys)`);
    if (typeof value !== "string") err(`notes "${key}" must be text`);
  }
}

function escapeRe(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function sameFeature(a, b, meta) {
  return JSON.stringify(normalizeFeature(a ?? {}, meta)) === JSON.stringify(normalizeFeature(b ?? {}, meta));
}

const labelOf = (value, set = STATUSES) => set.find((s) => s.id === value)?.label ?? "—";

/** One meeting-note line: `YYYY-MM-DD · <column>: <OLD> → <NEW> — <note>`. */
export function batchNoteLine(date, columnName, oldValue, newValue, note, set = STATUSES) {
  return `${date} · ${columnName}: ${labelOf(oldValue, set)} → ${labelOf(newValue, set)} — ${cleanText(note)}`;
}

/**
 * Set `column` to `value` ("unset" removes it) on the features of `doc` listed in `ids`.
 * Features already at `value` are skipped untouched. A non-empty `note` is appended to each
 * changed feature's `notes[noteKey]`. Ids of other components are ignored; ids of this
 * component that no longer exist are reported in `missing`. `doc` is not mutated.
 */
export function applyBatch(doc, ids, column, value, { noteKey, note = "", date, columnName, set = STATUSES, applies = () => true, own }) {
  const out = JSON.parse(JSON.stringify(doc));
  const wanted = new Set(ids);
  const changed = [];
  const skipped = [];
  const notApplicable = [];
  const text = cleanText(note);
  for (const feature of out.features ?? []) {
    if (!wanted.has(feature.id)) continue;
    if (!applies(feature)) {
      notApplicable.push(feature.id);
      continue;
    }
    const old = feature.status?.[column] || "unset";
    if (old === value) {
      skipped.push(feature.id);
      continue;
    }
    feature.status = { ...feature.status };
    if (value === "unset") delete feature.status[column];
    else feature.status[column] = value;
    if (!Object.keys(feature.status).length) delete feature.status;
    if (text && noteKey) {
      const line = batchNoteLine(date, columnName, old, value, text, set);
      const existing = cleanText(feature.notes?.[noteKey]);
      feature.notes = { ...feature.notes, [noteKey]: existing ? `${existing}\n\n${line}` : line };
    }
    changed.push(feature.id);
  }
  const present = new Set((out.features ?? []).map((f) => f.id));
  const missing = ids.filter((id) => (own ? own.has(id) : id.startsWith(`${doc.id}.`)) && !present.has(id));
  return { doc: out, changed, skipped, missing, notApplicable };
}

/** Commit message for a batch: `matrix-table: set <title> to <LABEL> for N feature(s)`. */
export function batchCommitMessage(columnTitle, value, n, { set = STATUSES, nouns = ["feature", "features"] } = {}) {
  return `matrix-table: set ${columnTitle} to ${labelOf(value, set)} for ${n} ${nouns[n === 1 ? 0 : 1]}`;
}

export function nextFeatureId(component) {
  const max = Math.max(0, ...component.features.map((f) => Number(f.id.split(".").pop()) || 0));
  return `${component.id}.${max + 1}`;
}

export function utf8ToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
