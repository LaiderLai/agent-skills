// Feature-matrix scenarios: every state ends in a DOM snapshot compared with tests/golden/feature/dom.
import { check, sleep } from "./cdp.mjs";
import { compareGolden, snapshot } from "./snapshot.mjs";
import { checkExportHtml } from "./export_html.mjs";

const SETTINGS = "matrixTable.settings";

export async function run({ page, baseUrl, repoFiles, goldenDir, update, fakeGithub }) {
  const snap = (name) => snapshot(page, name, goldenDir, update);
  const ready = (extra = "true") => page.waitFor(`document.querySelector("#content .loading") === null && document.querySelector("#content > *") && ${extra}`);
  const open = async (hash) => {
    await page.goto(`${baseUrl}/`);
    await page.evaluate(`location.hash = ${JSON.stringify(hash)}; location.reload()`);
    await sleep(300);
  };

  console.log("snapshot mode (not signed in)");
  await page.goto(`${baseUrl}/`);
  await page.evaluate(`localStorage.clear()`);
  await open("#/");
  await ready(`document.querySelector(".donut")`);
  await page.evaluate(`window.__blobs = []; const orig = URL.createObjectURL; URL.createObjectURL = (b) => { window.__blobs.push(b); return orig.call(URL, b); };`);
  await snap("overview");

  const donuts = await page.evaluate(`[...document.querySelectorAll("[data-focus]")].map((d) => d.dataset.focus)`);
  const focused = await page.evaluate(`document.querySelector(".donut.focused")?.dataset.focus`);
  const other = donuts.find((id) => id !== focused);
  check(other, `another column to focus (${other}, was ${focused})`);
  await page.click(`[data-focus="${other}"]`);
  await page.waitFor(`document.querySelector(".donut.focused")?.dataset.focus === ${JSON.stringify(other)}`);
  await snap(`overview-focus-${other}`);

  await page.click(`[data-action="export-csv"]`);
  const csv = await page.evaluate(`window.__blobs.at(-1).text()`);
  check(csv.includes("A.1.1"), "CSV export captured");
  compareGolden(goldenDir, "export.csv", csv, update);
  await checkExportHtml(page, "A.1");

  await open("#/c/A.1");
  await ready(`document.querySelector("[data-open]")`);
  await snap("component");

  await open("#/search?status=tbd");
  await ready(`document.querySelector("[data-open]")`);
  await snap("search-tbd");

  await open("#/c/A.1?open=A.1.1");
  await ready(`document.querySelector("#drawer.open h2")`);
  await snap("drawer-feature");

  await open("#/c/A.1?open=A.1");
  await ready(`document.querySelector("#drawer.open h2")`);
  await snap("drawer-component");

  console.log("live mode (signed in, fake GitHub)");
  await page.evaluate(`localStorage.setItem(${JSON.stringify(SETTINGS)}, JSON.stringify({ token: "test" }))`);
  await open("#/c/A.1?open=A.1.1");
  await ready(`document.querySelector("#source-badge.live") && document.querySelector('#drawer.open [data-action="edit"]')`);
  await page.click(`#drawer [data-action="edit"]`);
  await page.waitFor(`document.querySelector('#drawer [data-action="save"]')`);
  await snap("editor");

  const original = new Map(fakeGithub.files);
  await page.setField('#drawer [data-field="comment"]', "edited in browser test");
  await page.click(`#drawer .seg[data-column="board-x-ga"] [data-set-status="tbd"]`);
  await page.click(`#drawer [data-action="save"]`);
  await page.waitFor(`/Saved/.test(document.querySelector("#toasts")?.textContent ?? "")`);
  check(fakeGithub.commits.length === 1, "single-file save created one commit");
  const saved = fakeGithub.commits[0];
  const savedLines = [`message: ${saved.message}`];
  for (const path of Object.keys(saved.changes).sort()) savedLines.push(`\n=== ${path} ===`, saved.changes[path]);
  compareGolden(goldenDir, "editor-save.txt", savedLines.join("\n"), update);
  fakeGithub.commits.length = 0;
  for (const [p, t] of original) fakeGithub.files.set(p, t);

  await open("#/c/A.1");
  await ready(`document.querySelector("#source-badge.live") && document.querySelector("input[data-select]")`);
  for (const id of ["A.1.2", "A.1.3"]) await page.click(`input[data-select="${id}"]`);
  await page.waitFor(`document.querySelector("#batch-bar")`);
  await page.setField("#batch-column", "board-x-ga", "change");
  await page.click(`[data-batch-value="supported"]`);
  await snap("batch-bar");

  await page.setField("#batch-note", "agreed");
  await page.click(`[data-action="batch-apply"]`);
  await page.waitFor(`document.querySelector("#batch-confirm")`);
  await snap("batch-confirm");

  await page.click(`#batch-confirm [data-action="batch-confirm"]`);
  await page.waitFor(`/Saved 2 change/.test(document.querySelector("#toasts")?.textContent ?? "")`);
  check(fakeGithub.commits.length === 1, "exactly one commit created");
  const [commit] = fakeGithub.commits;
  const lines = [`message: ${commit.message}`];
  for (const path of Object.keys(commit.changes).sort()) lines.push(`\n=== ${path} ===`, commit.changes[path]);
  compareGolden(goldenDir, "batch-commit.txt", lines.join("\n"), update);
  check(Object.keys(commit.changes).length > 0 && Object.keys(commit.changes).every((p) => repoFiles.has(p)), "commit touches known files");

  fakeGithub.commits.length = 0;
  for (const [p, t] of original) fakeGithub.files.set(p, t);
  await open("#/c/A.1");
  await ready(`document.querySelector("#source-badge.live") && document.querySelector("input[data-select]")`);
  for (const id of ["A.1.2", "A.1.3"]) await page.click(`input[data-select="${id}"]`);
  await page.waitFor(`document.querySelector("#batch-bar")`);
  await page.setField("#batch-column", "soc", "change");
  await page.click(`[data-batch-value="supported"]`);
  check(await page.evaluate(`document.querySelector("#batch-note") === null`), "no meeting-note box for a column without platform");
  await page.click(`[data-action="batch-apply"]`);
  await page.waitFor(`document.querySelector("#batch-confirm")`);
  await page.click(`#batch-confirm [data-action="batch-confirm"]`);
  await page.waitFor(`/Saved [0-9]+ change/.test(document.querySelector("#toasts")?.textContent ?? "")`);
  const socCommit = fakeGithub.commits[0];
  check(Object.values(socCommit.changes).every((t) => !t.includes("→") && !t.includes("SoC:")), "no note written for column without platform");
  check(Object.values(socCommit.changes).every((t) => !/general:/.test(t)), "no general note written");

  fakeGithub.commits.length = 0;
  for (const [p, t] of original) fakeGithub.files.set(p, t);
  await open("#/c/A.1");
  await ready(`document.querySelector("#source-badge.live") && document.querySelector("input[data-select]")`);
  for (const id of ["A.1.2", "A.1.3"]) await page.click(`input[data-select="${id}"]`);
  await page.waitFor(`document.querySelector("#batch-bar")`);
  await page.setField("#batch-column", "board-x-ga", "change");
  await page.click(`[data-batch-value="supported"]`);
  await page.setField("#batch-note", "stale meeting note");
  await page.setField("#batch-column", "soc", "change");
  await page.click(`[data-batch-value="supported"]`);
  await page.click(`[data-action="batch-apply"]`);
  await page.waitFor(`document.querySelector("#batch-confirm")`);
  check(!(await page.evaluate(`document.querySelector("#batch-confirm").textContent`)).includes("Note added"), "confirm shows no note hint for stale note");
  await page.click(`#batch-confirm [data-action="batch-confirm"]`);
  await page.waitFor(`/Saved [0-9]+ change/.test(document.querySelector("#toasts")?.textContent ?? "")`);
  check(Object.values(fakeGithub.commits[0].changes).every((t) => !t.includes("stale meeting note")), "stale typed note not committed");

  await open("#/c/A.1?open=A.1.2");
  check(!(await page.evaluate(`document.querySelector("#drawer")?.textContent ?? ""`)).includes("General"), "feature drawer has no General");

  check(page.errors.length === 0, `no page errors${page.errors.length ? `: ${page.errors.join(" | ")}` : ""}`);
  check(fakeGithub.blocked.length === 0, `no requests to other hosts${fakeGithub.blocked.length ? `: ${fakeGithub.blocked.join(", ")}` : ""}`);
}
