// node tests/browser/run.mjs [--update] <suite>
// The browser DOM goldens need `google-chrome` locally; the unittest wrapper skips them (suite still OK) when it is missing.
import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { launch } from "./cdp.mjs";
import { fakeGithub } from "./fake_github.mjs";

// Node < 22 only has WebSocket behind a flag: re-run ourselves with it.
if (typeof WebSocket === "undefined") {
  const { status } = spawnSync(process.execPath, ["--experimental-websocket", ...process.argv.slice(1)], { stdio: "inherit" });
  process.exit(status ?? 1);
}

const HERE = dirname(fileURLToPath(import.meta.url));
const TESTS = resolve(HERE, "..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json" };

const SUITES = {
  requirement: { csv: "fixtures/requirement.csv", mapping: "fixtures/requirement-mapping.yaml", golden: "golden/requirement/dom", module: "./requirement.e2e.mjs" },
  feature: { csv: "fixtures/feature.csv", mapping: "fixtures/feature-mapping.yaml", golden: "golden/feature/dom", module: "./feature.e2e.mjs" },
};

const args = process.argv.slice(2);
const update = args.includes("--update");
const name = args.find((a) => !a.startsWith("--"));
const suite = SUITES[name];
if (!suite) {
  console.error(`usage: run.mjs [--update] <${Object.keys(SUITES).join("|")}>`);
  process.exit(1);
}

const freePort = () =>
  new Promise((ok, fail) => {
    const s = createServer().listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => ok(port));
    });
    s.on("error", fail);
  });

const work = mkdtempSync(join(tmpdir(), "matrix-browser-"));
let page, server;
let failed = false;
try {
  const out = execFileSync("python3", [join(TESTS, "golden_tool.py"), "--csv", join(TESTS, suite.csv), "--mapping", join(TESTS, suite.mapping), "--site-out", join(work, "repo")], { encoding: "utf8" });
  const dist = out.trim().split("\n").at(-1);
  // Maintenance hook: MATRIX_WEB_OVERRIDE=<dir> replaces the built site's web files (used to generate goldens from older assets).
  if (process.env.MATRIX_WEB_OVERRIDE) {
    for (const f of readdirSync(process.env.MATRIX_WEB_OVERRIDE)) copyFileSync(join(process.env.MATRIX_WEB_OVERRIDE, f), join(dist, f));
    rmSync(join(dist, "template.js"), { force: true });
  }
  const data = JSON.parse(readFileSync(join(dist, "data.json"), "utf8"));
  const { name: repo, branch, path } = data.meta.repository;
  const dataDir = join(dist, "..", "matrix-table", "data");
  const repoFiles = new Map(readdirSync(dataDir).filter((f) => f.endsWith(".yaml")).map((f) => [`${path}/${f}`, readFileSync(join(dataDir, f), "utf8")]));

  server = createServer((req, res) => {
    const file = join(dist, decodeURIComponent(new URL(req.url, "http://x").pathname === "/" ? "/index.html" : new URL(req.url, "http://x").pathname));
    if (!file.startsWith(dist)) return res.writeHead(403).end();
    try {
      const body = readFileSync(file);
      res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" }).end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  const sitePort = await freePort();
  await new Promise((r) => server.listen(sitePort, "127.0.0.1", r));

  page = await launch(await freePort());
  const fake = await fakeGithub(page, { repo, branch, files: repoFiles });
  const { run } = await import(suite.module);
  await run({ page, baseUrl: `http://127.0.0.1:${sitePort}`, repoFiles, goldenDir: join(TESTS, suite.golden), update, fakeGithub: fake });
  console.log(update ? "golden updated" : "PASS");
} catch (e) {
  console.error(e.message ?? e);
  failed = true;
} finally {
  page?.close();
  server?.close();
  rmSync(work, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
