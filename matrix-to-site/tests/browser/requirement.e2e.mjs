// Requirement-matrix scenarios: assertions only (no DOM snapshots), snapshot mode (not signed in).
import { load } from "../../assets/web/vendor/js-yaml.mjs";
import { check, sleep } from "./cdp.mjs";
import { checkExportHtml } from "./export_html.mjs";

export async function run({ page, baseUrl, fakeGithub }) {
  const ready = (extra = "true") => page.waitFor(`document.querySelector("#content .loading") === null && document.querySelector("#content > *") && ${extra}`);
  const open = async (hash, extra) => {
    await page.goto(`${baseUrl}/`);
    await page.evaluate(`localStorage.clear(); location.hash = ${JSON.stringify(hash)}; location.reload()`);
    await sleep(300);
    await ready(extra);
  };
  const text = (sel) => page.evaluate(`document.querySelector(${JSON.stringify(sel)})?.textContent.replace(/\\s+/g, " ").trim() ?? null`);
  const ids = () => page.evaluate(`[...document.querySelectorAll("tr[data-open]")].map((r) => r.dataset.open)`);
  const same = (got, want, what) => check(JSON.stringify(got) === JSON.stringify(want), `${what}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  const stat = (label) => page.evaluate(`[...document.querySelectorAll(".stat")].find((s) => s.querySelector(".stat-label")?.textContent.trim() === ${JSON.stringify(label)})?.querySelector(".stat-num").textContent.trim() ?? null`);
  const chipCounts = (field) => page.evaluate(`Object.fromEntries([...document.querySelectorAll('[data-chips="${field}"] .chip')].map((c) => [c.dataset.value || "all", Number(c.querySelector(".n").textContent)]))`);

  await page.goto(`${baseUrl}/`);
  await page.evaluate(`localStorage.clear(); localStorage.setItem("matrixTable.focus", "test")`);
  await page.evaluate(`location.hash = "#/"; location.reload()`);
  await sleep(300);
  await ready(`document.querySelector(".donut")`);
  same(await page.evaluate(`document.querySelector(".donut.focused")?.dataset.focus`), "fc", "stale test focus falls back to last phase with data");

  await open("#/", `document.querySelector(".donut")`);
  const donuts = await page.evaluate(`[...document.querySelectorAll("[data-focus]")].map((d) => d.dataset.focus)`);
  same(donuts, ["ea", "fc", "ga"], "phase donuts only");
  same(await text(`[data-focus="ea"] svg text`), "71%", "EA donut pct");
  check((await text(`[data-focus="ea"] svg`)).includes("done"), "donut labelled done");
  same(await text(`[data-focus="fc"] svg text`), "14%", "FC donut pct");
  check(!/resolved/i.test(await text("#content")), "no resolved wording on the overview");
  same(await page.evaluate(`document.querySelector(".donut.focused")?.dataset.focus`), "fc", "default focus");
  const head = await text(".page-head .sub");
  check(head?.includes("7 requirements in") && !head.includes("features"), `overview wording: ${head}`);
  same([await stat("Done"), await stat("Supported"), await stat("Enabled"), await stat("Not supported"), await stat("Not set")], ["14%", "0", "1", "0", "6"], "stat cards on FC");
  const risk = await text(".stat.risk");
  check(risk?.includes("0 / 3") && risk.includes("0%"), `risk card FC: ${risk}`);
  const lvl = (sel) => page.evaluate(`(document.querySelector(${JSON.stringify(sel)})?.className.match(/level-\\w+/) ?? [null])[0]`);
  same(await lvl(".stat.risk"), "level-red", "risk card level FC");
  check((await text(".stat.risk .stat-label")).startsWith("⚠"), "risk card warning mark");
  same(await lvl(".stat.coverage"), "level-red", "coverage card level");
  same(await lvl(".stat.tone-no"), null, "not supported card has no level on FC");
  const riskHref = await page.evaluate(`document.querySelector(".stat.risk").getAttribute("href")`);
  same(riskHref, "#/search?risk=risky", "risk href");
  const cov = await text(".stat.coverage");
  check(cov?.includes("Test coverage") && cov.includes("0%"), `coverage card pct: ${cov}`);
  check(cov.includes("YES 0 · NO 0 · TBD 7 · not set 0"), `coverage counts: ${cov}`);
  check(cov.includes("of 7 requirements"), `coverage denominator: ${cov}`);
  const nav = await text(".nav-home:nth-of-type(2)");
  check(nav?.includes("Not done") && !nav.includes("Open"), `sidebar link: ${nav}`);
  same(await text(".nav-home:nth-of-type(2) .count"), "6", "sidebar not done on FC");

  await page.click(`[data-focus="ea"]`);
  await page.waitFor(`document.querySelector(".donut.focused")?.dataset.focus === "ea"`);
  const riskEa = await text(".stat.risk");
  check(riskEa?.includes("2 / 3") && riskEa.includes("67%"), `risk card EA: ${riskEa}`);
  same(await lvl(".stat.risk"), "level-orange", "risk card level EA");
  same(await lvl(".stat.tone-no"), "level-red", "not supported level EA");
  check((await text(".stat.tone-no .stat-label")).startsWith("⚠"), "not supported warning mark");
  same(await page.evaluate(`document.querySelector(".stat.risk").getAttribute("href")`), riskHref, "risk href independent of phase");
  same(await stat("Done"), "71%", "done card follows focus");
  same(await text(".nav-home:nth-of-type(2) .count"), "2", "sidebar not done on EA");

  await open(riskHref, `document.querySelector("[data-open]")`);
  same(await ids(), ["2.03", "2.10", "2.16"], "risk card link rows");
  await open("#/search?risk=critical", `document.querySelector("[data-open]")`);
  same(await ids(), ["2.03", "2.16"], "risk=critical ignores excluded");
  check((await text("h1"))?.includes("requirements"), "search heading wording");
  check(await page.evaluate(`!!document.querySelector('[data-field-filter="risk"][data-value="critical"].active')`), "risk chip active");
  same(await chipCounts("risk"), { all: 9, none: 4, critical: 2, risky: 3 }, "risk chips ignore excluded and own filter");
  await open("#/search", `document.querySelector("[data-open]")`);
  const riskChips = await chipCounts("risk");
  same([riskChips.critical, riskChips.none, riskChips.risky], [2, 4, 3], "risk chip counts ignore excluded");
  const statusAll = await page.evaluate(`Number(document.querySelector('[data-status-filter=""] .n').textContent)`);
  same(statusAll, 9, "status All chip lists every row, excluded included");
  const scopeChips = await chipCounts("scope");
  same([scopeChips.all, scopeChips["out-of-scope"], riskChips.critical], [9, 2, 2], "scope All, Out-of-Scope and risk Critical chips");
  same([scopeChips["in-scope"], scopeChips.tbd], [6, 1], "scope chip counts");
  await open("#/search?scope=tbd", `document.querySelector("[data-open]")`);
  same(await ids(), ["2.10"], "scope=tbd");
  await open("#/search?scope=out-of-scope", `document.querySelector("[data-open]")`);
  same(await ids(), ["2.08.01", "4.01"], "scope=out-of-scope lists the excluded rows");
  await open("#/search?status=unset", `document.querySelector("[data-open]")`);
  same(await ids(), ["1.02", "2.01", "2.03", "2.10", "2.16", "3.01"], "not-set status filter skips excluded");

  await open("#/search?q=clocktest", `document.querySelector("[data-open]")`);
  same(await ids(), ["2.01"], "text search over list fields");

  await open("#/c/A.2", `document.querySelector("[data-open]")`);
  check(await page.evaluate(`document.querySelector("#chips-host [data-field-filter]") !== null`), "chips on component page");
  for (const id of ["2.08.01"]) {
    check(await page.evaluate(`document.querySelector('tr[data-open="${id}"]').classList.contains("excluded")`), `${id} row excluded`);
    check((await text(`tr[data-open="${id}"]`)).includes("Out of scope"), `${id} row says Out of scope`);
    check(await page.evaluate(`document.querySelector('tr[data-open="${id}"] input[data-select]') === null`), `${id} no checkbox`);
  }
  check(await page.evaluate(`!document.querySelector('tr[data-open="2.03"]').classList.contains("excluded")`), "2.03 not excluded");
  const riskCell = await page.evaluate(`document.querySelector('tr[data-open="2.03"] td.risk-critical')?.textContent.trim()`);
  check(riskCell === "Critical", `risk cell: ${riskCell}`);
  const heads = await page.evaluate(`[...document.querySelectorAll("tr.cols th")].map((t) => t.textContent.trim()).slice(0, 5)`);
  same(heads, ["ID", "Requirement", "Scope", "Risk", "EA"], "table headers");
  await open("#/c/A.4", `document.querySelector("[data-open]")`);
  check(await page.evaluate(`document.querySelector('tr[data-open="4.01"]').classList.contains("excluded")`), "4.01 row excluded");

  await open("#/c/A.2?open=2.08.01", `document.querySelector("#drawer.open h2")`);
  same(await page.evaluate(`[...document.querySelectorAll("#drawer [data-block]")].map((b) => b.dataset.block)`), ["requirements"], "excluded drawer blocks");
  const exDrawer = await text("#drawer");
  check(exDrawer.includes("Initial SoW") && exDrawer.includes("Out-of-Scope") && !exDrawer.includes("Risk") && !exDrawer.includes("PROJ-20") && !exDrawer.includes("Status"), `excluded drawer: ${exDrawer}`);

  await open("#/c/A.2?open=2.03", `document.querySelector("#drawer.open h2")`);
  same(await page.evaluate(`[...document.querySelectorAll("#drawer [data-block]")].map((b) => b.dataset.block)`), ["requirements", "discovery", "execution", "test-plan"], "2.03 drawer blocks");
  check(!(await text("#drawer")).includes("General"), "2.03 drawer has no General card or block");
  const disc = await text('#drawer [data-block="discovery"]');
  const fieldOf = (block, label) => page.evaluate(`[...document.querySelectorAll('#drawer [data-block="${block}"] .field-label')].find((l) => l.textContent.trim() === ${JSON.stringify(label)})?.nextElementSibling.textContent.trim() ?? null`);
  same([await fieldOf("discovery", "Discovery check"), await fieldOf("discovery", "Risk")], ["—", "Critical"], "discovery fields");
  check(disc.includes("needs workaround") && disc.includes("works with component"), `discovery block: ${disc}`);
  same(await page.evaluate(`[...document.querySelectorAll('#drawer [data-block="execution"] .exec-phase')].map((p) => [p.querySelector(".hint").textContent.trim(), p.querySelector(".pill").textContent.trim()])`), [["EA", "Enabled"], ["FC", "—"], ["GA", "—"]], "execution phases");
  const jira = await page.evaluate(`document.querySelector('#drawer .note-card a[href="https://example.atlassian.net/browse/PROJ-12"]')?.textContent`);
  check(jira === "PROJ-12", `PROJ-12 link in note card: ${jira}`);
  const noteHeads = await page.evaluate(`[...document.querySelectorAll("#drawer .note-card header")].map((h) => h.textContent)`);
  check(noteHeads.some((h) => h.startsWith("Discovery")) && !noteHeads.some((h) => h.startsWith("General")), `Discovery note card, no General: ${noteHeads}`);
  check(!noteHeads.some((h) => h.includes("Board X")), `no platform notes card: ${noteHeads}`);
  check(!(await text('#drawer [data-block="execution"]')).includes("Jira ID"), "no Jira ID in execution block");
  const plan = await text('#drawer [data-block="test-plan"] .test-plan');
  check(plan?.includes("Checkbox test type") && plan.includes("Checkbox test status"), `2.03 test plan: ${plan}`);
  check(!plan.includes("Test IDs") && !plan.includes("Test name"), "2.03 plan hides empty fields");
  check(await page.evaluate(`document.querySelectorAll("#drawer .note-card").length >= 1`), "note cards");
  check(!/resolved/i.test(await text("#drawer")), "no resolved wording in drawer");

  await open("#/c/A.2?open=2.01", `document.querySelector("#drawer.open h2")`);
  const plan1 = await text("#drawer .test-plan");
  check(plan1?.includes("Test IDs") && plan1.includes("cpu-001"), `2.01 test plan: ${plan1}`);

  await open("#/", `document.querySelector(".donut")`);
  await page.evaluate(`window.__blobs = []; const orig = URL.createObjectURL; URL.createObjectURL = (b) => { window.__blobs.push(b); return orig.call(URL, b); };`);
  await page.click(`[data-action="export-csv"]`);
  const csv = await page.evaluate(`window.__blobs.at(-1).text()`);
  const rows = csv.replace(/^\ufeff/, "").split("\r\n").map((r) => r.slice(1, -1).split('","'));
  const header = rows[0];
  check(["Scope", "Risk", "Test IDs", "Discovery notes"].every((h) => header.includes(h)), `csv header: ${header}`);
  check(!header.some((h) => ["Label", "Jira ID", "Board X notes"].includes(h)), `csv header has removed columns: ${header}`);
  check(["Discovery notes", "EA notes", "FC notes", "GA notes", "QA notes"].every((h) => header.includes(h)) && !header.includes("General notes"), `csv note columns: ${header}`);
  const kept = ["ID", "Section", "Component", "Requirement", "Comment", "Scope", "Source"];
  const ex = rows.find((r) => r[0] === "2.08.01");
  check(ex && ex[header.indexOf("Scope")] === "Out-of-Scope" && ex[header.indexOf("Source")] === "Initial SoW", `csv excluded row: ${ex}`);
  check(header.every((h, i) => kept.includes(h) || ex[i] === ""), `csv excluded row has empty cells after Requirements: ${ex}`);
  const row = rows.find((r) => r[0] === "2.03");
  check(row[header.indexOf("Board X · EA")] === "Enabled", `csv row 2.03: ${row}`);
  await checkExportHtml(page, "Hardware Configuration");

  console.log("hand-edited data: excluded item with data, item with empty scope");
  const patchData = `(() => {
    const orig = window.fetch;
    window.fetch = async (url, opts) => {
      const res = await orig(url, opts);
      if (!String(url).endsWith("data.json")) return res;
      const data = await res.json();
      for (const comp of data.components) for (const f of comp.doc.features) {
        if (f.id === "2.08.01") { f.status = { ea: "supported", test: "supported" }; f.fields.risk = "critical"; f.notes = { discovery: "ignored" }; }
        if (f.id === "2.01") delete f.fields.scope;
      }
      return new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });
    };
  })()`;
  const patched = await page.send("Page.addScriptToEvaluateOnNewDocument", { source: patchData });
  await open("#/", `document.querySelector(".donut")`);
  same(await text(`[data-focus="ea"] svg text`), "71%", "excluded status not counted, empty scope counted");
  await page.click(`[data-focus="ea"]`);
  await page.waitFor(`document.querySelector(".donut.focused")?.dataset.focus === "ea"`);
  check((await text(".stat.risk")).includes("2 / 3"), "excluded risk not counted");
  check((await text(".stat.coverage")).includes("TBD 7") && (await text(".stat.coverage")).includes("of 7 requirements"), "excluded test not counted; empty scope in coverage");
  await open("#/search?risk=critical", `document.querySelector("[data-open]")`);
  same(await ids(), ["2.03", "2.16"], "excluded risk not listed");
  await page.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: patched.identifier });

  console.log("labels from data are escaped");
  const patch = `(() => {
    const orig = window.fetch;
    window.fetch = async (url, opts) => {
      const res = await orig(url, opts);
      if (!String(url).endsWith("data.json")) return res;
      const data = await res.json();
      for (const set of Object.values(data.meta.status_sets)) set[0].label = "<b>x</b>";
      const col = data.meta.columns.find((c) => c.platform);
      for (const doc of data.components) for (const f of doc.doc?.features ?? doc.features ?? []) { f.status = { ...f.status, [col.id]: "<i>bad</i>" }; break; }
      return new Response(JSON.stringify(data), { status: 200, headers: { "content-type": "application/json" } });
    };
  })()`;
  const { identifier } = await page.send("Page.addScriptToEvaluateOnNewDocument", { source: patch });
  await open("#/", `document.querySelector(".donut")`);
  const injected = await page.evaluate(`[...document.querySelectorAll("#content b, #content i")].filter((e) => ["x", "bad"].includes(e.textContent)).length`);
  check(injected === 0, `no markup injected from labels (${injected})`);
  check((await text("#content"))?.includes("<b>x</b>"), "label shows as text");
  await open("#/c/A.2", `document.querySelector("[data-open]")`);
  check((await page.evaluate(`[...document.querySelectorAll("#content b, #content i")].filter((e) => ["x", "bad"].includes(e.textContent)).length`)) === 0, "no markup in table");
  await page.send("Page.removeScriptToEvaluateOnNewDocument", { identifier });

  console.log("live mode (signed in, fake GitHub)");
  const SETTINGS = "matrixTable.settings";
  const liveOpen = async (hash, extra = "true") => {
    await page.goto(`${baseUrl}/`);
    await page.evaluate(`localStorage.setItem(${JSON.stringify(SETTINGS)}, JSON.stringify({ token: "test" })); location.hash = ${JSON.stringify(hash)}; location.reload()`);
    await sleep(300);
    await ready(`document.querySelector("#source-badge.live") && ${extra}`);
  };
  await liveOpen("#/c/A.2", `document.querySelector("[data-open]")`);
  check(await page.evaluate(`document.querySelector('tr[data-open="2.03"] input[data-select]') !== null && document.querySelector('tr[data-open="2.08.01"] input[data-select]') === null`), "batch checkbox only on rows that are not excluded");
  await page.evaluate(`location.hash = "#/search"`);
  await ready(`document.querySelector("input[data-select]")`);
  await page.click(`input[data-select-all]`);
  same(await page.evaluate(`document.querySelectorAll("input[data-select]:checked").length`), 7, "select all skips excluded rows");

  const textOf = (c, n) => Object.entries(c.changes).find(([p]) => p.endsWith(n))?.[1] ?? "";
  const commitsNow = async (n) => {
    for (let i = 0; i < 100 && fakeGithub.commits.length < n; i++) await sleep(100);
    check(fakeGithub.commits.length === n, `commit count ${fakeGithub.commits.length}, want ${n}`);
    return fakeGithub.commits[n - 1];
  };
  const block = (yaml, id) => yaml.split(`- id: "${id}"`)[1]?.split("\n  - id:")[0] ?? "";
  const startEditing = async (hash) => {
    await liveOpen(hash, `document.querySelector('#drawer [data-action="edit"]')`);
    await page.click(`#drawer [data-action="edit"]`);
    await page.waitFor(`document.querySelector('#drawer [data-field="scope"]')`);
  };

  console.log("editing: scope Out-of-Scope keeps the other fields");
  await startEditing("#/c/A.1?open=1.02");
  check(!(await text("#drawer")).includes("ignored"), "no hint while in scope");
  const original = block([...fakeGithub.files].find(([p]) => p.endsWith("A.01-general.yaml"))[1], "1.02");
  await page.setField('#drawer [data-field="scope"]', "out-of-scope", "change");
  await page.waitFor(`document.querySelector("#drawer [data-excluded-hint]")`);
  check((await text("#drawer [data-excluded-hint]")).includes("ignored"), "hint says other fields are ignored");
  check(await page.evaluate(`document.querySelector('#drawer .status-grid') === null && document.querySelector('#drawer [data-field="risk"]') === null && document.querySelector('#drawer [data-field="notes.discovery"]') === null`), "other fields hidden");
  await page.click(`#drawer [data-action="save"]`);
  let commit = await commitsNow(1);
  let yaml = textOf(commit, "A.01-general.yaml");
  let b = block(yaml, "1.02");
  check(b.includes("scope: out-of-scope") && /ea: supported/.test(b) && /test: tbd/.test(b) && b.includes("uname desktop"), `1.02 kept data: ${b}`);

  await startEditing("#/c/A.1?open=1.02");
  await page.setField('#drawer [data-field="scope"]', "in-scope", "change");
  await page.waitFor(`document.querySelector('#drawer .status-grid')`);
  await page.click(`#drawer [data-action="save"]`);
  commit = await commitsNow(2);
  const b2 = block(textOf(commit, "A.01-general.yaml"), "1.02");
  check(b2.includes("scope: in-scope") && /ea: supported/.test(b2) && /test: tbd/.test(b2) && b2.includes("uname desktop"), `1.02 restored: ${b2}`);
  check(b2 === original, `1.02 identical to original:\n${b2}\nvs\n${original}`);

  console.log("batch");
  await liveOpen("#/search", `document.querySelector("input[data-select]")`);
  check(await page.evaluate(`document.querySelector('input[data-select="2.08.01"]') === null`), "2.08.01 is not tickable");
  for (const id of ["1.01", "2.16", "3.01"]) await page.click(`input[data-select="${id}"]`);
  await page.waitFor(`document.querySelector("#batch-bar")`);
  await page.setField("#batch-column", "ea", "change");
  await page.click(`[data-batch-value="supported"]`);
  await page.setField("#batch-note", "agreed");
  await page.click(`[data-action="batch-apply"]`);
  await page.waitFor(`document.querySelector("#batch-confirm")`);
  await page.click(`#batch-confirm [data-action="batch-confirm"]`);
  commit = await commitsNow(3);
  check(commit.message === "matrix-table: set Board X · EA to Supported for 2 requirements", `batch message: ${commit.message}`);
  const notes216 = block(textOf(commit, "A.02-hardware-configuration.yaml"), "2.16");
  const item216 = load(textOf(commit, "A.02-hardware-configuration.yaml")).features?.find?.((r) => r.id === "2.16") ?? {};
  check(typeof item216.notes?.ea === "string" && item216.notes.ea.trimEnd().endsWith("· EA: Not supported → Supported — agreed"), `2.16 note under ea: ${JSON.stringify(item216.notes)}`);
  check(Object.keys(item216.notes ?? {}).every((k) => ["ea", "discovery"].includes(k)), `2.16 no platform note keys: ${JSON.stringify(item216.notes)}`);
  check(!textOf(commit, "A.01-general.yaml").includes("agreed"), "1.01 skipped (already Supported)");

  await liveOpen("#/", `document.querySelector(".donut")`);
  same(await text(`[data-focus="ea"] svg text`), "100%", "EA donut after batch");

  console.log("new requirement");
  await liveOpen("#/c/A.4?open=new:A.4", `document.querySelector('#drawer [data-field-id]')`);
  check((await text("#drawer h2"))?.includes("New requirement"), "new requirement heading");
  const addNew = async (id) => {
    await page.setField("#drawer [data-field-id]", id);
    await page.setField('#drawer [data-field="name"]', "Reboot");
    await page.click(`#drawer [data-action="save"]`);
  };
  await addNew("5.01");
  commit = await commitsNow(4);
  check(textOf(commit, "A.04-process.yaml").includes('id: "5.01"'), "5.01 saved");
  await liveOpen("#/c/A.4?open=new:A.4", `document.querySelector('#drawer [data-field-id]')`);
  await addNew("5.01");
  await page.waitFor(`document.querySelector("#drawer .errors")?.textContent.includes("already exists")`);
  await addNew("A.1");
  await page.waitFor(`document.querySelector("#drawer .errors")?.textContent.includes("A.1 already exists")`);
  check(fakeGithub.commits.length === 4, "duplicate ids not committed");

  await startEditing("#/c/A.2?open=2.16");
  same(await page.evaluate(`[...document.querySelectorAll('#drawer .seg[data-column="ea"] button')].map((x) => x.textContent.trim())`), ["Supported", "Enabled", "Not supported", "—"], "editor EA value buttons");
  check(await page.evaluate(`document.querySelector('#drawer [data-field="label"]') === null && document.querySelector('#drawer [data-field="notes.platform-1"]') === null && document.querySelector('#drawer [data-field="notes.general"]') === null && document.querySelector('#drawer [data-field="notes.discovery"]') !== null`), "editor has no label, platform or general notes");

  check(page.errors.length === 0, `page errors: ${page.errors.join(" | ")}`);
}
