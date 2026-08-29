// CDP helper: node cdp_eval.mjs <port> <js-expression>
const port = process.argv[2];
const js = process.argv[3];
const mode = process.argv[4] || 'eval';
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
const page = list.find(t => (t.type === 'page' || t.type === 'browser_ui') && t.webSocketDebuggerUrl);
if (!page) { console.log('NO PAGE TARGET'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
let r;
if (mode === 'nav') {
  r = await send('Page.navigate', { url: js });
} else {
  r = await send('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true });
}
console.log(JSON.stringify(r.result, null, 1));
ws.close();
