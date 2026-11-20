#!/usr/bin/env node
// Usage:
//   node tools/build.mjs check          validate data/*.yaml and verify canonical formatting
//   node tools/build.mjs format         rewrite data/*.yaml into the canonical formatting
//   node tools/build.mjs build <dir>    validate, then write the static site (web/ + data.json) to <dir>
import { readFileSync, writeFileSync, readdirSync, mkdirSync, cpSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parseYaml, dumpComponent, validateComponent } from "../web/model.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dataDir = join(root, "data");
const [command, outDir] = process.argv.slice(2);
let gitTop;

const meta = parseYaml(readFileSync(join(dataDir, "_meta.yaml"), "utf8"));
const files = readdirSync(dataDir)
  .filter((name) => name.endsWith(".yaml") && !name.startsWith("_"))
  .sort();

const errors = [];
const unformatted = [];
const components = [];
const featureIds = new Map();

for (const name of files) {
  const path = join(dataDir, name);
  const text = readFileSync(path, "utf8");
  let doc;
  try {
    doc = parseYaml(text);
  } catch (e) {
    errors.push(`${name}: YAML syntax error: ${e.message}`);
    continue;
  }
  errors.push(...validateComponent(doc, meta, name));
  for (const feature of doc?.features ?? []) {
    if (featureIds.has(feature.id)) errors.push(`${name}: feature id ${feature.id} is also used in ${featureIds.get(feature.id)}`);
    featureIds.set(feature.id, name);
  }
  const canonical = dumpComponent(doc, meta);
  if (canonical !== text) {
    if (command === "format") writeFileSync(path, canonical);
    else unformatted.push(name);
  }
  components.push({ path: `matrix-table/data/${name}`, doc });
}

if (errors.length) {
  console.error(errors.map((e) => `error: ${e}`).join("\n"));
  process.exit(1);
}

if (command === "check") {
  if (unformatted.length) {
    console.error(unformatted.map((n) => `error: ${n} is not canonically formatted`).join("\n"));
    console.error("Run: node matrix-table/tools/build.mjs format");
    process.exit(1);
  }
  console.log(`OK: ${files.length} components, ${featureIds.size} features`);
} else if (command === "format") {
  console.log(`Formatted ${files.length} files`);
} else if (command === "build" && outDir) {
  if (unformatted.length) console.warn(`warning: not canonically formatted: ${unformatted.join(", ")}`);
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(join(outDir, "versions"), { recursive: true });
  cpSync(join(root, "web"), outDir, { recursive: true });
  const versions = gitVersions();
  for (const version of versions) {
    writeFileSync(join(outDir, "versions", version.file), JSON.stringify(loadFromGit(version.tag)));
  }
  const data = { generated: new Date().toISOString(), meta, components, versions };
  writeFileSync(join(outDir, "data.json"), JSON.stringify(data));
  console.log(`Built site into ${outDir} (${components.length} components, ${featureIds.size} features, ${versions.length} versions)`);
} else {
  console.error("usage: build.mjs check | format | build <dir>");
  process.exit(2);
}

// Versions are annotated git tags named <tag_prefix><version>.
function gitVersions() {
  const prefix = meta.repository?.tag_prefix ?? "matrix-table/";
  let out;
  try {
    out = git("for-each-ref", `refs/tags/${prefix}`, "--sort=-creatordate", "--format=%(refname:strip=2)%00%(creatordate:iso-strict)%00%(taggername)%(if)%(taggername)%(then)%(else)%(committername)%(end)%00%(contents)%01");
  } catch (e) {
    console.warn(`warning: cannot list version tags: ${e.message}`);
    return [];
  }
  return out
    .split("\x01")
    .map((record) => record.replace(/^\n/, ""))
    .filter(Boolean)
    .map((record) => {
      const [tag, date, tagger, message] = record.split("\0");
      const name = tag.slice(prefix.length);
      return { name, tag, date, tagger, message: message.trim(), file: `${name.replace(/[^\w.-]/g, "_")}.json` };
    });
}

function loadFromGit(tag) {
  const dataPath = meta.repository?.path ?? "matrix-table/data";
  const names = git("ls-tree", "--name-only", `${tag}:${dataPath}`).split("\n").filter((n) => n.endsWith(".yaml"));
  const read = (name) => parseYaml(git("show", `${tag}:${dataPath}/${name}`));
  return {
    meta: read("_meta.yaml"),
    components: names.filter((n) => !n.startsWith("_")).sort().map((n) => ({ path: `${dataPath}/${n}`, doc: read(n) })),
  };
}

function git(...args) {
  const run = (cwd, a) => execFileSync("git", a, { cwd, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "pipe"] });
  gitTop ??= run(root, ["rev-parse", "--show-toplevel"]).trim();
  return run(gitTop, args);
}
