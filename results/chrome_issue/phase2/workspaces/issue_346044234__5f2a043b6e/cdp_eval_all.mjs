// CDP helper: node cdp_eval_all.mjs <port> <js-expression> — evaluates on ALL page-like targets, prints index + result
const port = process.argv[2];
const js = process.argv[3];
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
const pages = list.filter(t => (t.type === 'page' || t.type === 'browser_ui') && t.webSocketDebuggerUrl);
for (let i = 0; i < pages.length; i++) {
  const page = pages[i];
  try {
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let id = 0; const pending = new Map();
    ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
    const send = (method, params = {}) => new Promise(res => { const idn = ++id; pending.set(idn, res); ws.send(JSON.stringify({ id: idn, method, params })); });
    const r = await send('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true });
    console.log(`TARGET ${i} (${page.type}): ${JSON.stringify(r.result)}`);
    ws.close();
  } catch (e) { console.log(`TARGET ${i} ERROR: ${e.message}`); }
}
