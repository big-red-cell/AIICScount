// node cdp_eval_target.mjs <port> <index> <js>
const port = process.argv[2];
const idx = parseInt(process.argv[3]);
const js = process.argv[4];
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
const pages = list.filter(t => (t.type === 'page' || t.type === 'browser_ui') && t.webSocketDebuggerUrl);
const page = pages[idx];
if (!page) { console.log('NO TARGET ' + idx); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const r = await send('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true });
console.log(JSON.stringify(r.result));
ws.close();
