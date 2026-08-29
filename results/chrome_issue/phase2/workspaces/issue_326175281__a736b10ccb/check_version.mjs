// Read chrome://version DOM for profile path and command line
const PORT = 9222;
const BASE = `http://127.0.0.1:${PORT}`;

async function main() {
  const targets = await (await fetch(`${BASE}/json/list`)).json();
  const t = targets.find((x) => x.type === 'page');
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id) { const p = pending.get(msg.id); if (p) { pending.delete(msg.id); msg.error ? p.rej(new Error(JSON.stringify(msg.error))) : p.res(msg.result); } }
    else if (msg.method) { for (const l of listeners) l(msg); }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id; pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const onEvent = (fn) => listeners.add(fn);
  await send('Page.enable');
  await send('Runtime.enable');
  const loadP = new Promise((res) => { const h = (m) => { if (m.method === 'Page.loadEventFired') { listeners.delete(h); res(); } }; onEvent(h); });
  await send('Page.navigate', { url: 'chrome://version' });
  await loadP;
  await new Promise((r) => setTimeout(r, 1200));
  const r = await send('Runtime.evaluate', { expression: `(() => { const t = document.body.innerText; const i = t.indexOf('Profile Path'); return t.slice(i, i + 200); })()`, returnByValue: true });
  console.log('PROFILE_INFO=' + JSON.stringify(r.result.value));
  process.exit(0);
}
main().catch((e) => { console.error('ERR ' + e.message); process.exit(1); });
