import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "../assets/web/vendor/js-yaml.mjs";
import { validateMeta } from "../assets/web/template.js";
import { validateComponent } from "../assets/web/model.js";

const reqMeta = () =>
  load(`
template: requirement-matrix
exclude_when: {field: scope, equals: out-of-scope}
noun: [requirement, requirements]
sections: [{id: A, name: Requirements}]
platforms: [{id: platform-1, name: Platform 1}]
status_sets:
  requirement:
    - {id: supported, label: Supported, resolved: true, tone: yes}
    - {id: out-of-scope, label: Out-of-Scope, resolved: true, tone: neutral}
    - {id: tbd, label: TBD, resolved: false, tone: open}
fields:
  - {id: scope, name: Scope, type: enum, show: table, filter: true, values: [{id: in-scope, label: In Scope}, {id: out-of-scope, label: Out-of-Scope, tone: neutral}]}
  - {id: source, name: Source, type: text, show: detail}
  - {id: bugs, name: Bugs, type: list, show: detail, link: jira}
note_keys:
  - {id: x01, name: x01}
  - {id: qa, name: QA}
columns:
  - {id: p1-x01, name: x01, platform: platform-1, status_set: requirement, note_key: x01}
  - {id: test, name: Test, group: Test plan, role: test, status_set: requirement, note_key: qa}
`);
const featMeta = () => ({ sections: [{ id: "A", name: "S" }], platforms: [{ id: "p1" }], columns: [{ id: "c1", name: "C", platform: "p1" }] });
const has = (errors, text) => assert.ok(errors.some((e) => e.includes(text)), `${text} in ${JSON.stringify(errors)}`);

test("feature meta", () => {
  assert.deepEqual(validateMeta({ ...featMeta(), extra: 1 }), []);
  has(validateMeta({ ...featMeta(), fields: [] }), '"fields"');
  has(validateMeta({ ...featMeta(), note_keys: [] }), '"note_keys"');
  const m = featMeta();
  m.columns[0].status_set = "x";
  has(validateMeta(m), '"status_set"');
});

test("requirement meta", () => {
  assert.deepEqual(validateMeta(reqMeta()), []);
  let m = reqMeta();
  m.status_sets.requirement[0].tone = "purple";
  has(validateMeta(m), "tone");
  m = reqMeta();
  m.columns[0].status_set = "nope";
  has(validateMeta(m), "not defined");
  m = reqMeta();
  m.note_keys[0].id = "general";
  has(validateMeta(m), "reserved");
  m = reqMeta();
  m.exclude_when = { field: "source", equals: "x" };
  has(validateMeta(m), "enum field");
  m = reqMeta();
  m.exclude_when = { field: "scope", equals: "nope" };
  has(validateMeta(m), "not a value");
  m = reqMeta();
  m.exclude_when = "scope";
  has(validateMeta(m), "exclude_when must be a mapping");
  has(validateMeta({ ...featMeta(), exclude_when: { field: "scope", equals: "x" } }), '"exclude_when"');
  m = featMeta();
  m.columns[0].applies_when = {};
  has(validateMeta(m), '"applies_when"');
  m = reqMeta();
  m.status_sets.default = [];
  has(validateMeta(m), "reserved");
});

const item = (o) => ({ id: "2.1", name: "GPU", ...o });
const doc = (...features) => ({ id: "A.1", name: "Cat", features });

test("requirement items", () => {
  const meta = reqMeta();
  assert.deepEqual(validateComponent(doc(item({ id: "2.08.01", fields: { scope: "in-scope", bugs: ["B-1"] }, status: { test: "tbd" } })), meta, "f"), []);
  has(validateComponent(doc(item({ id: 2.1 })), meta, "f"), "quoted string");
  has(validateComponent(doc(item({ fields: { scope: "maybe" } })), meta, "f"), "in-scope, out-of-scope");
  assert.deepEqual(validateComponent(doc(item({ fields: { scope: "out-of-scope", bugs: ["B-1"] }, status: { test: "tbd", "p1-x01": "supported" }, notes: { qa: "ok" } })), meta, "f"), []);
  has(validateComponent(doc(item({ fields: { scope: "out-of-scope" }, status: { test: "bogus" } })), meta, "f"), "one of supported");
  has(validateComponent(doc(item({ status: { "p1-x01": "bogus" } })), meta, "f"), "one of supported");
  has(validateComponent(doc(item({ notes: { qa: "ok", zzz: "x" } })), meta, "f"), 'notes key "zzz"');
});

test("requirement items reject label and platform notes", () => {
  const meta = reqMeta();
  has(validateComponent(doc(item({ label: "x" })), meta, "f"), 'unknown key "label"');
  has(validateComponent(doc(item({ notes: { "platform-1": "x" } })), meta, "f"), 'notes key "platform-1"');
  has(validateComponent(doc(item({ notes: { general: "Jira: B-1" } })), meta, "f"), "re-import");
});

test("feature item with label still passes", () => {
  assert.deepEqual(validateComponent(doc({ id: "A.1.1", name: "n", label: "x" }), featMeta(), "f"), []);
});

test("feature item with fields is unknown key", () => {
  has(validateComponent(doc({ id: "A.1.1", name: "n", fields: {} }), featMeta(), "f"), 'unknown key "fields"');
});

test("validateMeta reports malformed input instead of throwing", () => {
  const bad = (patch, text) => {
    const meta = { ...reqMeta(), ...patch };
    let errors;
    assert.doesNotThrow(() => (errors = validateMeta(meta)));
    has(errors, text);
  };
  bad({ status_sets: { a: [null] } }, 'status set "a": entries must be mappings');
  bad({ status_sets: { a: [{ id: "x", resolved: true, tone: "yes" }] } }, 'status "x" in set "a" needs id and label');
  bad({ status_sets: { a: [{ id: "x", label: "X", tone: "yes" }] } }, "resolved must be true or false");
  bad({ status_sets: { a: [{ id: "x", label: "X", resolved: "yes", tone: "yes" }] } }, "resolved must be true or false");
  bad({ columns: [null] }, "column 1 must be a mapping");
  bad({ fields: [null] }, "field 1 must be a mapping");
  bad({ note_keys: [null] }, "note key 1 must be a mapping");
  bad({ platforms: [null] }, "platform 1 must be a mapping");
  bad({ columns: "nope" }, '"columns" must be a list');
  has(validateMeta({ columns: [null] }), "column 1 must be a mapping");
  assert.deepEqual(validateMeta({ ...featMeta(), extra_key: 1 }), []);
});

test("requirement column applies_when is obsolete", () => {
  const m = reqMeta();
  m.columns[0].applies_when = { field: "scope", equals: "in-scope" };
  has(validateMeta(m), '_meta.yaml: column "p1-x01": applies_when is obsolete, use exclude_when');
});

test("requirement column needs a known note_key", () => {
  let m = reqMeta();
  delete m.columns[0].note_key;
  has(validateMeta(m), "note_key");
  m = reqMeta();
  m.columns[0].note_key = "nope";
  has(validateMeta(m), "note_key");
});

test("general notes are rejected with a re-import hint", () => {
  has(validateComponent(doc({ id: "A.1.1", name: "n", notes: { general: "x" } }), featMeta(), "f"), "re-import");
  has(validateComponent({ ...doc({ id: "A.1.1", name: "n" }), notes: { general: "x" } }, featMeta(), "f"), "re-import");
  has(validateComponent({ ...doc(item({})), notes: { general: "x" } }, reqMeta(), "f"), "re-import");
});
