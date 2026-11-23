import { test } from "node:test";
import assert from "node:assert/strict";
import { applyBatch, batchNoteLine, sameFeature, batchCommitMessage } from "../assets/web/model.js";

const doc = () => ({
  id: "A.1",
  name: "System",
  features: [
    { id: "A.1.1", name: "Boot", status: { "b-beta": "tbd" }, notes: { b: "old" } },
    { id: "A.1.2", name: "Reboot", status: { "b-beta": "unsupported" } },
    { id: "A.1.3", name: "Suspend", status: { "b-beta": "supported" }, notes: { general: "keep" } },
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
  assert.deepEqual(f["A.1.3"].notes, { general: "keep" });
});

test("empty note leaves notes alone", () => {
  const r = applyBatch(doc(), ["A.1.1", "A.1.2"], "b-beta", "supported", opts({ note: "   " }));
  const f = byId(r.doc);
  assert.deepEqual(f["A.1.1"].notes, { b: "old" });
  assert.equal(f["A.1.2"].notes, undefined);
});

test("note under general for a column without platform", () => {
  const r = applyBatch(doc(), ["A.1.2"], "b-beta", "tbd", opts({ noteKey: "general", note: "revisit" }));
  assert.equal(byId(r.doc)["A.1.2"].notes.general, "2026-11-23 · Beta: NO → TBD — revisit");
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
