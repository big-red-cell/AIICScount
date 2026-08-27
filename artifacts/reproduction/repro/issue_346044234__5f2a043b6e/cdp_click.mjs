// node cdp_click.mjs <port> <targetIndex> <x> <y>
const port = process.argv[2];
const idx = parseInt(process.argv[3]);
const x = parseInt(process.argv[4]);
const y = parseInt(process.argv[5]);
const list = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json());
const pages = list.filter(t => (t.type === 'page' || t.type === 'browser_ui') && t.webSocketDebuggerUrl);
const page = pages[idx];
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
console.log(`clicked ${x},${y} on target ${idx}`);
ws.close();
