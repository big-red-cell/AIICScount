// CDP driver: navigate to the local PoC page, click the moniker link, read back state.
const WS = "ws://127.0.0.1:9222/devtools/page/NEW"; // replaced below
const fs = require("fs");

function getJson(url, method = "GET") {
  return new Promise((res, rej) => {
    const http = require("http");
    const req = http.request(url, { method }, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => {
        try { res(JSON.parse(d)); } catch (e) { rej(new Error("bad json: " + d)); }
      });
    });
    req.on("error", rej);
    req.end();
  });
}

async function main() {
  // Create a new tab targeting the PoC file URL directly (about:blank then navigate).
  const target = await getJson(
    "http://127.0.0.1:9222/json/new?about:blank",
    "PUT"
  );
  const wsUrl = target.webSocketDebuggerUrl;
  console.log("TARGET_URL=" + wsUrl);

  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  const events = [];

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    } else if (msg.method) {
      events.push(msg);
    }
  };

  const send = (method, params = {}) =>
    new Promise((res, rej) => {
      const mid = ++id;
      pending.set(mid, (m) => (m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result)));
      ws.send(JSON.stringify({ id: mid, method, params }));
    });

  await new Promise((res) => (ws.onopen = res));
  await send("Page.enable");
  await send("Runtime.enable");

  const fileUrl = "file:///D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_325707095__d75fad8179/exploit.html";
  await send("Page.navigate", { url: fileUrl });
  await new Promise((r) => setTimeout(r, 2500));

  let r = await send("Runtime.evaluate", { expression: "document.title + '|' + location.href + '|' + document.querySelector('a') ? document.querySelector('a').getAttribute('href') : 'NOANCHOR'" , returnByValue: true });
  console.log("PAGE_STATE=" + JSON.stringify(r.result.value));

  // Click the link via DOM (synthetic click triggers navigation the same as a user click).
  r = await send("Runtime.evaluate", { expression: "(function(){ var a = document.querySelector('a'); a.click(); return 'clicked'; })()", returnByValue: true });
  console.log("CLICK_RESULT=" + JSON.stringify(r.result.value));

  // Sample the active tab state over the next few seconds.
  for (let i = 0; i < 8; i++) {
    await new Promise((r2) => setTimeout(r2, 500));
    try {
      const rr = await send("Runtime.evaluate", { expression: "location.href", returnByValue: true });
      console.log("T+ " + (i + 1) * 500 + "ms URL=" + JSON.stringify(rr.result.value));
    } catch (e) {
      console.log("T+ " + (i + 1) * 500 + "ms EVAL_ERR=" + e.message);
    }
  }

  fs.writeFileSync(
    "D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_325707095__d75fad8179/cdp_events.json",
    JSON.stringify(events, null, 1)
  );
  console.log("DONE");
  ws.close();
  process.exit(0);
}

main().catch((e) => {
  console.error("FATAL " + e.message);
  process.exit(1);
});
