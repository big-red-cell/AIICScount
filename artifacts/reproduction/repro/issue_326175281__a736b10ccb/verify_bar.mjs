// Verify bar visibility via innerHeight + navigate to lure page, then click the in-page lure link
// (fallback evidence) — and attempt CDP mouse click at bookmarks-bar coordinates (negative/zero y).
const PORT = 9222;
const BASE = `http://127.0.0.1:${PORT}`;

async function getTargets() {
  const res = await fetch(`${BASE}/json/list`);
  return res.json();
}

async function main() {
  const targets = await getTargets();
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
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true });
    return r.result.value;
  };
  await send('Runtime.enable');
  await send('Page.enable');

  const ih = await evalJs('window.innerHeight');
  console.log('INNER_H=' + ih + ' (807 = bar hidden, ~778 = bar visible)');

  // navigate to lure page
  const loadP = new Promise((res) => { const h = (m) => { if (m.method === 'Page.loadEventFired') { listeners.delete(h); res(); } }; onEvent(h); });
  await send('Page.navigate', { url: 'http://127.0.0.1:8765/lure.html' });
  await loadP;
  await new Promise((r) => setTimeout(r, 800));
  console.log('URL=' + await evalJs('location.href'));
  console.log('TITLE=' + await evalJs('document.title'));
  console.log('RECT=' + await evalJs(`JSON.stringify((()=>{const r=document.querySelector('a#lure img').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})())`));
  process.exit(0);
}
main().catch((e) => { console.error('ERR ' + e.message); process.exit(1); });
