// CDP repro driver for issue 375594906__cc64ce1591
// Site: https://mrnoob790.github.io/os
// Claim: holding Enter clicks a webkitdirectory file input; after picking a
// directory, the page writes files[0].webkitRelativePath into #qmsg, which can
// include the OS username as a path component.
const SITE = "https://mrnoob790.github.io/os";
const ROOT_DIR = "D:\\Codes\\agents\\aiic_three_stage_pipeline\\artifacts\\reproduction\\repro\\issue_375594906__cc64ce1591\\sandbox\\home";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
  const page = list.find((t) => t.type === "page");
  console.log("TARGET:", page.url, "|", page.title, "|", page.webSocketDebuggerUrl);

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const send = (method, params = {}) => new Promise((res) => {
    const mid = ++id;
    pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) return { exception: r.result.exceptionDetails.text };
    return r.result.result.value;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("DOM.enable");

  // 1. Navigate
  await send("Page.navigate", { url: SITE });
  await sleep(4000);
  console.log("STEP1 nav:", await evaluate("location.href + ' | ' + document.title"));
  console.log("STEP1 html:", await evaluate("document.body.innerHTML.length + ' bytes'"));
  console.log("STEP1 hasInput:", await evaluate("!!document.getElementById('thing') && document.getElementById('thing').getAttribute('webkitdirectory')"));

  // 2. Hold-enter flow: patch click to observe, then dispatch 5 Enter keydowns
  console.log("STEP2 hook:", await evaluate(
    "window.__clicked=false; HTMLInputElement.prototype.click=function(){window.__clicked=true;}; true"
  ));
  for (let i = 0; i < 5; i++) {
    await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  }
  await sleep(300);
  console.log("STEP2 clicked:", await evaluate("window.__clicked"));
  console.log("STEP2 handlerNulled:", await evaluate("document.onkeydown === null"));

  // 3. Set directory on the webkitdirectory input via CDP (equivalent to picking a folder)
  const doc = await send("DOM.getDocument", { depth: -1 });
  const q = await send("DOM.querySelector", { nodeId: doc.result.root.nodeId, selector: "#thing" });
  const nodeId = q.result.nodeId;
  console.log("STEP3 nodeId:", nodeId);
  const setRes = await send("DOM.setFileInputFiles", { nodeId, files: [ROOT_DIR] });
  console.log("STEP3 setFiles:", JSON.stringify(setRes));
  await sleep(2000); // directory enumeration + change event

  // 4. Readback: what did the page display?
  console.log("STEP4 qmsg:", await evaluate("document.getElementById('qmsg').innerHTML"));
  console.log("STEP4 filesLen:", await evaluate("document.getElementById('thing').files.length"));
  console.log("STEP4 relPath0:", await evaluate("document.getElementById('thing').files.length ? document.getElementById('thing').files[0].webkitRelativePath : '(none)'"));
  console.log("STEP4 name0:", await evaluate("document.getElementById('thing').files.length ? document.getElementById('thing').files[0].name : '(none)'"));
  console.log("STEP4 usernameInQmsg:", await evaluate("document.getElementById('qmsg').innerHTML.toLowerCase().includes('znnnnnh2')"));

  ws.close();
}
main().catch((e) => { console.error("FATAL:", e); process.exit(1); });
