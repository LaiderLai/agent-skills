// Export HTML check: click "Export HTML", open the downloaded report from file:// (no server),
// and confirm it renders. Needs the URL.createObjectURL hook that stores blobs in window.__blobs.
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { check } from "./cdp.mjs";

export async function checkExportHtml(page, expectText) {
  const before = await page.evaluate(`window.__blobs.filter((b) => b.type === "text/html").length`);
  await page.click(`[data-action="export-html"]`);
  await page.waitFor(`window.__blobs.filter((b) => b.type === "text/html").length > ${before}`);
  const html = await page.evaluate(`window.__blobs.filter((b) => b.type === "text/html").at(-1).text()`);
  const dir = mkdtempSync(join(tmpdir(), "matrix-export-"));
  const file = join(dir, "report.html");
  writeFileSync(file, html);
  const errorsBefore = page.errors.length;
  try {
    await page.goto(`file://${file}`);
    try {
      await page.waitFor(`document.querySelector("#content .loading") === null && document.querySelector("#content > *")`, 10000);
    } catch {
      check(false, `exported HTML still loading after 10 s (${page.errors.slice(errorsBefore).join("; ")})`);
    }
    const text = await page.evaluate(`document.querySelector("#content").innerText`);
    const errors = page.errors.slice(errorsBefore);
    check(!errors.length, `exported HTML opens from file:// without errors (${errors.join("; ")})`);
    check(await page.evaluate(`document.body.classList.contains("exported")`), "exported HTML renders as a report");
    check(text.includes(expectText), `exported HTML shows "${expectText}"`);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
