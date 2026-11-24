import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "../assets/web/vendor/js-yaml.mjs";
import { TONES, isRequirement, noun, statusSet, statusInfo, tally, noteKeyFor, noteOrder, testColumn, coverage, excluded, included, done, risky, riskDone, coverageLevel, riskLevel, notSupportedLevel } from "../assets/web/template.js";

const meta = load(`
template: requirement-matrix
noun: [requirement, requirements]
status_sets:
  requirement:
    - {id: supported,     label: Supported,     resolved: true,  tone: yes}
    - {id: enabled,       label: Enabled,       resolved: true,  tone: info}
    - {id: not-supported, label: Not supported, resolved: true,  tone: no}
    - {id: out-of-scope,  label: Out-of-Scope,  resolved: true,  tone: neutral}
    - {id: tbd,           label: TBD,           resolved: false, tone: open}
note_keys:
  - {id: discovery, name: Discovery}
  - {id: x01, name: x01}
columns:
  - {id: p1-x01, name: x01, platform: platform-1, status_set: requirement, note_key: x01}
  - {id: p1-x02, name: x02, platform: platform-1, status_set: requirement}
  - {id: test, name: Test, group: Test plan, role: test, note_key: qa}
`);
meta.platforms = [{ id: "platform-1" }];
const [c1, c2, tcol] = meta.columns;
const plain = { columns: [], platforms: [] };
const item = (status, fields = {}) => ({ id: "x", status: { col: status }, fields });

test("tones and template detection", () => {
  assert.deepEqual(TONES, ["yes", "no", "open", "neutral", "info", "warn"]);
  assert.equal(isRequirement(meta), true);
  assert.equal(isRequirement(plain), false);
});

test("noun", () => {
  assert.equal(noun(plain, 1), "feature");
  assert.equal(noun(plain, 2), "features");
  assert.equal(noun(meta, 1), "requirement");
  assert.equal(noun(meta, 0), "requirements");
});

test("statusSet", () => {
  assert.deepEqual(statusSet(plain, { id: "a" }).map((s) => s.id), ["supported", "unsupported", "tbd"]);
  assert.deepEqual(statusSet(plain, { id: "a", status_set: "default" }).map((s) => s.tone), ["yes", "no", "open"]);
  assert.equal(statusSet(meta, c1).length, 5);
});

test("statusInfo", () => {
  assert.deepEqual(statusInfo(plain, {}, "supported"), { label: "YES", title: "Resolved – supported / in scope", cls: "supported" });
  const i = statusInfo(meta, c1, "enabled");
  assert.equal(i.cls, "tone-info");
  assert.equal(i.label, "Enabled");
  assert.deepEqual(statusInfo(meta, c1, "unset"), { label: "—", title: "Not set", cls: "unset" });
});

test("tally", () => {
  const items = ["supported", "enabled", "out-of-scope", "tbd", undefined].map((s) => ({ id: "x", status: { "p1-x01": s } }));
  const t = tally(items, meta, c1);
  assert.equal(t.resolved, 3);
  assert.equal(t.open, 1);
  assert.equal(t.unset, 1);
  assert.equal(t.total, 5);
  assert.equal(t.values.enabled, 1);
});

test("note keys", () => {
  assert.equal(noteKeyFor(c1, meta), "x01");
  assert.equal(noteKeyFor(c2, plain), "platform-1");
  assert.equal(noteKeyFor(c2, meta), null);
  assert.equal(noteKeyFor({ id: "z" }, meta), null);
  assert.equal(noteKeyFor({ id: "f" }, plain), null);
  assert.equal(noteKeyFor({ id: "r", platform: "p" }, { template: "requirement-matrix" }), null);
  const req = { template: "requirement-matrix" };
  assert.equal(noteKeyFor({ id: "e", platform: "p", note_key: "ea" }, req), "ea");
  assert.deepEqual(noteOrder({ platforms: [{ id: "p1" }, { id: "p2" }] }), ["p1", "p2"]);
  assert.deepEqual(noteOrder({ template: "requirement-matrix", note_keys: ["discovery", "ea", "fc", "ga", "qa"].map((id) => ({ id })) }), ["discovery", "ea", "fc", "ga", "qa"]);
  assert.equal(testColumn(meta), tcol);
  assert.equal(testColumn(plain), undefined);
});

const xmeta = load(`
template: requirement-matrix
exclude_when: {field: scope, equals: out-of-scope}
status_sets:
  execution:
    - {id: supported, label: Supported, resolved: true, tone: yes}
    - {id: enabled, label: Enabled, resolved: true, tone: info}
    - {id: not-supported, label: Not supported, resolved: false, tone: no}
fields:
  - {id: scope, name: Scope, type: enum, values: [{id: in-scope, label: In}, {id: out-of-scope, label: Out}, {id: tbd, label: TBD}]}
  - {id: risk, name: Risk, type: enum, values: [{id: none, label: None}, {id: critical, label: Critical}]}
columns:
  - {id: ea, name: EA, status_set: execution}
  - {id: fc, name: FC, status_set: execution}
  - {id: test, name: Test, role: test}
`);
const [ea] = xmeta.columns;
const it = (id, scope, risk, status = {}) => ({ id, fields: { ...(scope && { scope }), ...(risk && { risk }) }, status });
const xitems = [
  it("A", "in-scope", "none", { ea: "supported", test: "supported" }),
  it("B", "in-scope", "critical", { ea: "enabled", test: "tbd" }),
  it("C", "tbd", undefined, { ea: "not-supported" }),
  it("D", undefined, "critical"),
  it("E", "out-of-scope", "critical", { ea: "supported", test: "supported" }),
];
const ids = (l) => l.map((f) => f.id);

test("exclusion, done, risk and coverage", () => {
  assert.equal(excluded(xmeta, xitems[4]), true);
  assert.equal(excluded(xmeta, xitems[3]), false);
  assert.equal(excluded(plain, xitems[4]), false);
  assert.deepEqual(ids(included(xitems, xmeta)), ["A", "B", "C", "D"]);
  assert.deepEqual(done(included(xitems, xmeta), xmeta, ea), { done: 2, total: 4, pct: 50 });
  assert.deepEqual(done([], xmeta, ea), { done: 0, total: 0, pct: 0 });
  assert.deepEqual(ids(risky(xitems, xmeta)), ["B", "C", "D"]);
  const rd = riskDone(xitems, xmeta, ea);
  assert.deepEqual({ done: rd.done, total: rd.total, pct: rd.pct }, { done: 1, total: 3, pct: 33 });
  assert.deepEqual(ids(rd.items), ["B", "C", "D"]);
  assert.deepEqual(coverage(xitems, xmeta), { total: 4, yes: 1, no: 0, tbd: 1, unset: 2, pct: 25 });
  assert.equal(coverage([], xmeta).pct, 0);
});

test("countNoun keeps the historical plural for feature matrices", async () => {
  const { countNoun } = await import("../assets/web/template.js");
  assert.equal(countNoun({}, 1), "features");
  assert.equal(countNoun({ template: "feature-matrix" }, 1), "features");
  const req = { template: "requirement-matrix", noun: ["requirement", "requirements"] };
  assert.equal(countNoun(req, 1), "requirement");
  assert.equal(countNoun(req, 2), "requirements");
});

test("unknown status value falls back to raw label and counts as unset", () => {
  const meta = { columns: [{ id: "c1", name: "C" }] };
  const column = meta.columns[0];
  assert.deepEqual(statusInfo(meta, column, "<b>x</b>"), { label: "<b>x</b>", title: "<b>x</b>", cls: "unset" });
  const t = tally([{ status: { c1: "bogus" } }, { status: { c1: "supported" } }], meta, column);
  assert.equal(t.unset, 1);
  assert.equal(t.values.supported, 1);
});

test("warning levels", () => {
  const c = (pct, total = 10) => coverageLevel({ pct, total });
  assert.deepEqual([0, 49, 50, 79, 80, 99, 100].map((p) => c(p)), ["red", "red", "orange", "orange", "yellow", "yellow", "green"]);
  assert.equal(c(0, 0), null);
  const r = (d, t) => riskLevel({ done: d, total: t, pct: t ? Math.round((d / t) * 100) : 0 });
  assert.deepEqual([r(0, 3), r(1, 3), r(2, 3), r(3, 3), r(0, 0)], ["red", "orange", "orange", "green", "green"]);
  assert.equal(riskLevel({ done: 99, total: 100, pct: 99 }), "orange");
  assert.equal(r(199, 200), "orange");
  assert.equal(r(1, 300), "orange");
  assert.equal(notSupportedLevel(0), null);
  assert.equal(notSupportedLevel(1), "red");
});
