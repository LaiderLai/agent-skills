import { test } from "node:test";
import assert from "node:assert/strict";
import { excluded } from "../assets/web/template.js";
import { applyBatch, batchNoteLine, sameFeature, batchCommitMessage } from "../assets/web/model.js";

const doc = () => ({
  id: "A.1",
  name: "System",
  features: [
    { id: "A.1.1", name: "Boot", status: { "b-beta": "tbd" }, notes: { b: "old" } },
    { id: "A.1.2", name: "Reboot", status: { "b-beta": "unsupported" } },
    { id: "A.1.3", name: "Suspend", status: { "b-beta": "supported" }, notes: { b: "keep" } },
  ],
});
const opts = (extra = {}) => ({ noteKey: "b", note: "", date: "2026-11-23", columnName: "Beta", ...extra });
const byId = (d) => Object.fromEntries(d.features.map((f) => [f.id, f]));

test("applies value and skips already-set", () => {
  const r = applyBatch(doc(), ["A.1.1", "A.1.2", "A.1.3"], "b-beta", "supported", opts());
  assert.deepEqual(r.changed, ["A.1.1", "A.1.2"]);
  assert.deepEqual(r.skipped, ["A.1.3"]);
  assert.deepEqual(r.missing, []);
  for (const f of r.doc.features) assert.equal(f.status["b-beta"], "supported");
});

test("appends note under platform key", () => {
  const r = applyBatch(doc(), ["A.1.1", "A.1.2", "A.1.3"], "b-beta", "supported", opts({ note: "  agreed " }));
  const f = byId(r.doc);
  assert.equal(f["A.1.1"].notes.b, "old\n\n2026-11-23 · Beta: TBD → YES — agreed");
  assert.equal(f["A.1.2"].notes.b, "2026-11-23 · Beta: NO → YES — agreed");
  assert.deepEqual(f["A.1.3"].notes, { b: "keep" });
});

test("empty note leaves notes alone", () => {
  const r = applyBatch(doc(), ["A.1.1", "A.1.2"], "b-beta", "supported", opts({ note: "   " }));
  const f = byId(r.doc);
  assert.deepEqual(f["A.1.1"].notes, { b: "old" });
  assert.equal(f["A.1.2"].notes, undefined);
});

test("null note key changes status but writes no note", () => {
  const r = applyBatch(doc(), ["A.1.2"], "b-beta", "tbd", opts({ noteKey: null, note: "agreed" }));
  assert.equal(byId(r.doc)["A.1.2"].status["b-beta"], "tbd");
  assert.equal(byId(r.doc)["A.1.2"].notes, undefined);
});

test("unset removes status key", () => {
  const r = applyBatch(doc(), ["A.1.3"], "b-beta", "unset", opts({ note: "dropped" }));
  const f = byId(r.doc)["A.1.3"];
  assert.equal("b-beta" in (f.status ?? {}), false);
  assert.match(f.notes.b, /YES → —/);
  assert.deepEqual(r.changed, ["A.1.3"]);
});

test("unset on a feature that has no value is skipped", () => {
  const d = doc();
  delete d.features[1].status;
  const r = applyBatch(d, ["A.1.2"], "b-beta", "unset", opts());
  assert.deepEqual(r.skipped, ["A.1.2"]);
});

test("ids of other components and unknown ids", () => {
  const r = applyBatch(doc(), ["A.1.1", "B.2.1", "A.1.9"], "b-beta", "supported", opts());
  assert.deepEqual(r.changed, ["A.1.1"]);
  assert.deepEqual(r.missing, ["A.1.9"]);
});

test("does not mutate input", () => {
  const d = doc();
  const before = JSON.stringify(d);
  applyBatch(d, ["A.1.1", "A.1.2"], "b-beta", "supported", opts({ note: "x" }));
  assert.equal(JSON.stringify(d), before);
});

test("batchNoteLine uses status labels", () => {
  assert.equal(batchNoteLine("2026-11-23", "GA", "unset", "unsupported", "out of scope"), "2026-11-23 · GA: — → NO — out of scope");
});

test("sameFeature ignores key order and empty values", () => {
  assert.equal(sameFeature({ id: "A.1.1", name: "x", label: "" }, { name: "x", id: "A.1.1" }), true);
  assert.equal(sameFeature({ id: "A.1.1", name: "x" }, { id: "A.1.1", name: "y" }), false);
});

test("batchCommitMessage pluralises and labels the value", () => {
  assert.equal(batchCommitMessage("Board B · Beta", "supported", 1), "matrix-table: set Board B · Beta to YES for 1 feature");
  assert.equal(batchCommitMessage("Board B · Beta", "unsupported", 2), "matrix-table: set Board B · Beta to NO for 2 features");
  assert.equal(batchCommitMessage("Silicon", "unset", 3), "matrix-table: set Silicon to — for 3 features");
});

const REQ = [
  { id: "supported", label: "Supported", resolved: true },
  { id: "enabled", label: "Enabled", resolved: true },
  { id: "tbd", label: "TBD", resolved: false },
];

test("batchNoteLine uses a custom status set", () => {
  assert.equal(batchNoteLine("2026-11-23", "x01", "enabled", "supported", "ok", REQ), "2026-11-23 · x01: Enabled → Supported — ok");
});

test("batchCommitMessage uses custom set and nouns", () => {
  const nouns = ["requirement", "requirements"];
  assert.equal(batchCommitMessage("x01", "enabled", 1, { set: REQ, nouns }), "matrix-table: set x01 to Enabled for 1 requirement");
  assert.equal(batchCommitMessage("x01", "enabled", 2, { set: REQ, nouns }), "matrix-table: set x01 to Enabled for 2 requirements");
});

test("applyBatch skips items where the column does not apply", () => {
  const r = applyBatch(doc(), ["A.1.1", "A.1.2"], "b-beta", "supported", opts({ applies: (f) => f.id !== "A.1.2" }));
  assert.deepEqual(r.changed, ["A.1.1"]);
  assert.deepEqual(r.notApplicable, ["A.1.2"]);
  assert.equal(byId(r.doc)["A.1.2"].status["b-beta"], "unsupported");
});

test("applyBatch with own set reports missing ids", () => {
  const r = applyBatch(doc(), ["A.1.1", "2.99", "3.1"], "b-beta", "supported", opts({ own: new Set(["A.1.1", "2.99"]) }));
  assert.deepEqual(r.missing, ["2.99"]);
});

test("excluded items land in notApplicable", () => {
  const meta = { exclude_when: { field: "scope", equals: "out-of-scope" } };
  const d = doc();
  d.features[1].fields = { scope: "out-of-scope" };
  const r = applyBatch(d, ["A.1.1", "A.1.2"], "b-beta", "supported", opts({ applies: (f) => !excluded(meta, f) }));
  assert.deepEqual(r.notApplicable, ["A.1.2"]);
});
