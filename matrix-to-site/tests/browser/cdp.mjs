// Minimal Chrome DevTools Protocol driver for headless browser tests.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch(port) {
  const profile = mkdtempSync(join(tmpdir(), "matrix-chrome-"));
  // Downloads (and Chrome's partial-download temp files) go inside the throwaway profile,
  // set before launch, so nothing can ever land in the user's ~/Downloads.
  const downloadDir = join(profile, "downloads");
  mkdirSync(join(profile, "Default"), { recursive: true });
  mkdirSync(downloadDir);
  writeFileSync(
    join(profile, "Default", "Preferences"),
    JSON.stringify({ download: { default_directory: downloadDir, prompt_for_download: false }, savefile: { default_directory: downloadDir } }),
  );
  const chrome = spawn(
    "google-chrome",
    ["--headless=new", "--no-sandbox", "--disable-gpu", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--window-size=1440,1000", "about:blank"],
    { stdio: ["ignore", "ignore", process.env.CDP_DEBUG ? "inherit" : "ignore"], detached: true },
  );
  const stop = () => {
    try {
      process.kill(-chrome.pid, "SIGKILL");
    } catch {}
    rmSync(profile, { recursive: true, force: true });
  };
  let ws;
  for (let i = 0; i < 75 && !ws; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) ws = new WebSocket(page.webSocketDebuggerUrl);
    } catch (e) { if (process.env.CDP_DEBUG) console.error(e); }
    if (!ws) await sleep(200);
  }
  if (!ws) {
    stop();
    throw new Error("could not connect to Chrome");
  }
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0;
  const pending = new Map();
  const listeners = new Map();
  const errors = [];
  ws.addEventListener("message", (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
      return;
    }
    for (const fn of listeners.get(msg.method) ?? []) fn(msg.params);
    if (msg.method === "Runtime.exceptionThrown") errors.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
    else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") errors.push(JSON.stringify(msg.params.args.map((a) => a.value ?? a.description)));
  });
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const msgId = ++id;
      pending.set(msgId, { resolve, reject });
      ws.send(JSON.stringify({ id: msgId, method, params }));
    });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`eval failed: ${expression}\n${JSON.stringify(r.exceptionDetails)}`);
    return r.result.value;
  };
  await send("Page.enable");
  await send("Runtime.enable");
  // Exports are read from the page (blob hook); keep any real download inside the profile.
  await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloadDir });
  return {
    send,
    evaluate,
    errors,
    downloadDir,
    on(method, fn) {
      listeners.set(method, [...(listeners.get(method) ?? []), fn]);
    },
    async goto(url) {
      await send("Page.navigate", { url });
      await sleep(300);
    },
    async waitFor(expression, timeout = 30000) {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        if (await evaluate(`Boolean(${expression})`)) return;
        await sleep(100);
      }
      throw new Error(`timeout waiting for ${expression}\n${await evaluate("document.body.innerText.slice(0,300)")}`);
    },
    click: (sel) => evaluate(`document.querySelector(${JSON.stringify(sel)}).click()`),
    setField: (sel, value, event = "input") =>
      evaluate(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); el.value = ${JSON.stringify(value)};
        el.dispatchEvent(new Event(${JSON.stringify(event)}, { bubbles: true })); })()`),
    close() {
      try {
        ws.close();
      } catch {}
      stop();
    },
  };
}

export function check(cond, msg) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  console.log(`  ✓ ${msg}`);
}
