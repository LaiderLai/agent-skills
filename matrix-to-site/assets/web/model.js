// Shared data model for the matrix table: used by the web editor (browser)
// and by tools/build.mjs (Node, CI) so both write byte-identical YAML.
import { load, dump } from "./vendor/js-yaml.mjs";

// YES / NO are resolved decisions (done); TBD is open and needs attention.
export const STATUSES = [
  { id: "supported", label: "YES", resolved: true, title: "Resolved – supported / in scope" },
  { id: "unsupported", label: "NO", resolved: true, title: "Resolved – not supported / out of scope" },
  { id: "tbd", label: "TBD", resolved: false, title: "Open – not yet verified, still under discussion" },
];
export const STATUS_IDS = STATUSES.map((s) => s.id);
export const GENERAL = "general";

const COMPONENT_KEYS = ["id", "name", "description", "notes", "features"];
const FEATURE_KEYS = ["id", "name", "label", "comment", "status", "notes"];

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
  const order = [GENERAL, ...(meta?.platforms ?? []).map((p) => p.id)];
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

export function normalizeFeature(feature, meta) {
  const out = {
    id: cleanText(feature.id),
    name: cleanText(feature.name),
    label: cleanText(feature.label),
    comment: cleanText(feature.comment),
    status: orderedStatus(feature.status, meta),
    notes: orderedNotes(feature.notes, meta),
  };
  if (out.label === out.name) out.label = "";
  for (const key of Object.keys(feature)) {
    if (!FEATURE_KEYS.includes(key)) out[key] = feature[key];
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
  const noteKeys = [GENERAL, ...(meta.platforms ?? []).map((p) => p.id)];

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
      if (!FEATURE_KEYS.includes(key)) ferr(`unknown key "${key}"`);
    }
    if (!new RegExp(`^${escapeRe(component.id)}\\.\\d+$`).test(feature.id ?? "")) {
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
          if (value && !STATUS_IDS.includes(value)) ferr(`status "${column}: ${value}" must be one of ${STATUS_IDS.join(", ")}`);
        }
      }
    }
    checkNotes(feature.notes, noteKeys, ferr);
  });
  return errors;
}

function checkNotes(notes, allowed, err) {
  if (notes === undefined) return;
  if (typeof notes !== "object" || Array.isArray(notes)) return err("notes must be a mapping");
  for (const [key, value] of Object.entries(notes)) {
    if (!allowed.includes(key)) err(`notes key "${key}" must be one of ${allowed.join(", ")}`);
    if (typeof value !== "string") err(`notes "${key}" must be text`);
  }
}

function escapeRe(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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
