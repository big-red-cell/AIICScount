// Control A/B: reload PoC page (no click) -> watch 445; then click -> watch 445.
const fs = require("fs");
const http = require("http");

function getJson(url, method = "GET") {
  return new Promise((res, rej) => {
    const req = http.request(url, { method }, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => { try { res(JSON.parse(d)); } catch (e) { rej(new Error("bad json: " + d)); } });
    });
    req.on("error", rej);
    req.end();
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const targets = await getJson("http://127.0.0.1:9222/json/list");
  const page = targets.find((t) => t.type === "page");
  console.log("PAGE_WS=" + page.webSocketDebuggerUrl + " URL=" + page.url);
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, (m) => (m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result)));
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  await new Promise((res) => (ws.onopen = res));
  await send("Page.enable");
  await send("Runtime.enable");

  const fileUrl = "file:///D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_325707095__d75fad8179/exploit.html";

  // Phase A: reload page, wait, no click. Check for 445 connections during this window.
  await send("Page.navigate", { url: fileUrl });
  await sleep(3000);
  let r = await send("Runtime.evaluate", { expression: "location.href + '|' + document.querySelector('a').getAttribute('href')", returnByValue: true });
  console.log("A_LOADED=" + JSON.stringify(r.result.value));
  console.log("A_SLEEP_BEGIN " + new Date().toISOString());
  await sleep(4000);
  console.log("A_SLEEP_END " + new Date().toISOString());

  // Phase B: click the link.
  r = await send("Runtime.evaluate", { expression: "(function(){ document.querySelector('a').click(); return 'clicked'; })()", returnByValue: true });
  console.log("B_CLICK=" + JSON.stringify(r.result.value) + " @ " + new Date().toISOString());
  await sleep(12000);
  try {
    r = await send("Runtime.evaluate", { expression: "location.href", returnByValue: true });
    console.log("B_FINAL_URL=" + JSON.stringify(r.result.value) + " @ " + new Date().toISOString());
  } catch (e) { console.log("B_EVAL_ERR=" + e.message); }
  console.log("DONE");
  ws.close();
  process.exit(0);
}
main().catch((e) => { console.error("FATAL " + e.message); process.exit(1); });
