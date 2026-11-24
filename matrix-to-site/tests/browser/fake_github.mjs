// In-memory stand-in for the GitHub REST calls the web app makes, served through CDP Fetch.
// Every request to a host other than localhost / api.github.com is blocked and recorded.
import { createHash } from "node:crypto";

const sha1 = (text) => createHash("sha1").update(text).digest("hex");
const blobSha = (text) => sha1(`blob ${Buffer.byteLength(text)}\0${text}`);
const b64 = (text) => Buffer.from(text, "utf8").toString("base64");

export async function fakeGithub(page, { repo, branch, files }) {
  const state = { files: new Map(files), commits: [], blocked: [], requests: [] };
  const blobs = new Map(); // sha -> text, for every text ever stored
  const trees = new Map(); // tree sha -> [{path, sha}]
  const created = new Map(); // commit sha -> { message, tree }
  let head = sha1("initial-head");
  const remember = (text) => {
    const sha = blobSha(text);
    blobs.set(sha, text);
    return sha;
  };
  for (const text of state.files.values()) remember(text);

  const route = (method, url, body) => {
    const u = new URL(url);
    const path = decodeURIComponent(u.pathname);
    const base = `/repos/${repo}`;
    if (method === "GET" && path === "/user") return { login: "tester", name: "Tester" };
    if (method === "GET" && path === base) return { full_name: repo, permissions: { push: true } };
    if (method === "GET" && path === `${base}/git/matching-refs/tags/matrix-table/`) return [];
    if (method === "GET" && path.startsWith(`${base}/contents/`)) {
      const file = path.slice(`${base}/contents/`.length);
      if (state.files.has(file)) {
        const text = state.files.get(file);
        return { type: "file", name: file.split("/").pop(), path: file, sha: blobSha(text), content: b64(text), encoding: "base64" };
      }
      const prefix = `${file}/`;
      const listing = [...state.files].filter(([p]) => p.startsWith(prefix)).map(([p, t]) => ({ type: "file", name: p.slice(prefix.length), path: p, sha: blobSha(t) }));
      return listing.length ? listing : { status: 404, message: "Not Found" };
    }
    let m;
    if (method === "GET" && (m = path.match(new RegExp(`^${base}/git/blobs/([0-9a-f]+)$`)))) {
      return blobs.has(m[1]) ? { sha: m[1], content: b64(blobs.get(m[1])), encoding: "base64" } : { status: 404, message: "Not Found" };
    }
    if (method === "GET" && path === `${base}/git/ref/heads/${branch}`) return { ref: `refs/heads/${branch}`, object: { type: "commit", sha: head } };
    if (method === "GET" && (m = path.match(new RegExp(`^${base}/git/commits/([0-9a-f]+)$`)))) return { sha: m[1], tree: { sha: sha1(`tree-of-${m[1]}`) } };
    if (method === "POST" && path === `${base}/git/blobs`) {
      const text = Buffer.from(body.content, "base64").toString("utf8");
      return { sha: remember(text) };
    }
    if (method === "POST" && path === `${base}/git/trees`) {
      const sha = sha1(JSON.stringify(body.tree));
      trees.set(sha, body.tree);
      return { sha };
    }
    if (method === "POST" && path === `${base}/git/commits`) {
      const sha = sha1(`commit ${created.size} ${body.message} ${body.tree}`);
      created.set(sha, { message: body.message, tree: body.tree });
      return { sha, html_url: `https://github.com/${repo}/commit/${sha}`, tree: { sha: body.tree } };
    }
    if (method === "PATCH" && path === `${base}/git/refs/heads/${branch}`) {
      const commit = created.get(body.sha);
      if (!commit) return { status: 422, message: "Object does not exist" };
      const changes = {};
      for (const { path: p, sha } of trees.get(commit.tree)) {
        changes[p] = blobs.get(sha);
        state.files.set(p, blobs.get(sha));
      }
      state.commits.push({ message: commit.message, changes });
      head = body.sha;
      return { ref: `refs/heads/${branch}`, object: { type: "commit", sha: head } };
    }
    if (method === "PUT" && path.startsWith(`${base}/contents/`)) {
      const file = path.slice(`${base}/contents/`.length);
      const text = Buffer.from(body.content, "base64").toString("utf8");
      state.files.set(file, text);
      remember(text);
      state.commits.push({ message: body.message, changes: { [file]: text } });
      head = sha1(`put ${state.commits.length}`);
      return { content: { sha: blobSha(text) }, commit: { sha: head, html_url: `https://github.com/${repo}/commit/${head}` } };
    }
    return { status: 404, message: `fake GitHub: unhandled ${method} ${path}` };
  };

  const cors = [
    { name: "access-control-allow-origin", value: "*" },
    { name: "access-control-allow-headers", value: "*" },
    { name: "access-control-allow-methods", value: "GET,POST,PUT,PATCH,DELETE,OPTIONS" },
  ];

  page.on("Fetch.requestPaused", async ({ requestId, request }) => {
    const url = new URL(request.url);
    if (process.env.CDP_DEBUG) console.error("req", request.method, request.url);
    try {
      if (url.protocol === "file:" || url.hostname === "127.0.0.1" || url.hostname === "localhost") {
        await page.send("Fetch.continueRequest", { requestId });
      } else if (url.hostname === "api.github.com") {
        if (request.method === "OPTIONS") {
          await page.send("Fetch.fulfillRequest", { requestId, responseCode: 204, responseHeaders: cors });
          return;
        }
        const body = request.postData ? JSON.parse(request.postData) : undefined;
        state.requests.push(`${request.method} ${url.pathname}`);
        const result = route(request.method, request.url, body);
        const status = result?.status ?? 200;
        await page.send("Fetch.fulfillRequest", {
          requestId,
          responseCode: status,
          responseHeaders: [...cors, { name: "content-type", value: "application/json" }],
          body: Buffer.from(JSON.stringify(result)).toString("base64"),
        });
      } else {
        state.blocked.push(request.url);
        await page.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
      }
    } catch (e) {
      state.blocked.push(`handler error for ${request.url}: ${e.message}`);
    }
  });
  await page.send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  return state;
}
