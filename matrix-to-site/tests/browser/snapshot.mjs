import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const SELECTORS = ["#content", "#drawer", "#batch-bar", "#dialog"];

/** Replace everything that differs between runs: dates, ISO times, shas, local ports, blob URLs. */
export function normalise(text) {
  return text
    .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?/g, "<time>")
    .replace(/\d{4}-\d{2}-\d{2}/g, "<date>")
    .replace(/\b[0-9a-f]{40}\b/g, "<sha40>")
    .replace(/\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7}\b/g, "<sha7>")
    .replace(/(?:127\.0\.0\.1|localhost):\d+/g, "localhost:<port>")
    .replace(/blob:[^\s"'<>]+/g, "blob:<url>");
}

/** Compare (or with `update`, write) goldenDir/<file> against text. */
export function compareGolden(goldenDir, file, text, update) {
  const path = join(goldenDir, file);
  const out = normalise(text);
  if (update) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, out, "utf8");
    return;
  }
  if (!existsSync(path)) throw new Error(`missing golden file ${path} (run with --update)`);
  const want = readFileSync(path, "utf8");
  if (want !== out) {
    const a = want.split("\n");
    const b = out.split("\n");
    const i = a.findIndex((line, n) => line !== b[n]);
    throw new Error(`${file} differs from golden at line ${i + 1}:\n  golden: ${(a[i] ?? "").slice(0, 300)}\n  actual: ${(b[i] ?? "").slice(0, 300)}`);
  }
}

export async function snapshot(page, name, goldenDir, update) {
  const parts = [];
  for (const sel of SELECTORS) {
    const html = await page.evaluate(`document.querySelector(${JSON.stringify(sel)})?.outerHTML ?? null`);
    parts.push(`<!-- ${sel} -->\n${html ?? "(absent)"}\n`);
  }
  compareGolden(goldenDir, `${name}.html`, parts.join("\n"), update);
  const sidebar = await page.evaluate(`document.querySelector("#sidebar")?.outerHTML ?? null`);
  compareGolden(goldenDir, `${name}.sidebar.html`, `<!-- #sidebar -->\n${sidebar ?? "(absent)"}\n`, update);
  console.log(`  ✓ snapshot ${name}`);
}
