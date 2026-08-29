// Test F6 focus traversal via CDP keys.
// Probe: install keydown listener in page; dispatch F6 then 'x'.
// If F6 moved focus to browser chrome (omnibox/bar), page receives no 'x'.
const PORT = 9222;
const BASE = `http://127.0.0.1:${PORT}`;

async function getTargets() {
  const res = await fetch(`${BASE}/json/list`);
  return res.json();
}

async function main() {
  const targets = await getTargets();
  // pick the lure page target (has title Anti-bot Checker)
  const t = targets.find((x) => x.type === 'page' && x.title.includes('Anti-bot'));
  if (!t) { console.log('NO_LURE_TARGET ' + JSON.stringify(targets.map((x) => x.title))); process.exit(1); }
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id) { const p = pending.get(msg.id); if (p) { pending.delete(msg.id); msg.error ? p.rej(new Error(JSON.stringify(msg.error))) : p.res(msg.result); } }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id; pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const key = async (params) => { await send('Input.dispatchKeyEvent', params); };
  await send('Runtime.enable');
  await send('Page.enable');

  await send('Runtime.evaluate', { expression: `window.__keys = []; window.addEventListener('keydown', (e) => window.__keys.push(e.key)); 'listener-installed'` });
  await new Promise((r) => setTimeout(r, 300));

  // F6 twice, then 'x'
  await key({ type: 'rawKeyDown', modifiers: 0, key: 'F6', code: 'F6', windowsVirtualKeyCode: 117, nativeVirtualKeyCode: 117 });
  await key({ type: 'keyUp', modifiers: 0, key: 'F6', code: 'F6', windowsVirtualKeyCode: 117, nativeVirtualKeyCode: 117 });
  await new Promise((r) => setTimeout(r, 400));
  await key({ type: 'rawKeyDown', modifiers: 0, key: 'F6', code: 'F6', windowsVirtualKeyCode: 117, nativeVirtualKeyCode: 117 });
  await key({ type: 'keyUp', modifiers: 0, key: 'F6', code: 'F6', windowsVirtualKeyCode: 117, nativeVirtualKeyCode: 117 });
  await new Promise((r) => setTimeout(r, 400));
  await key({ type: 'rawKeyDown', modifiers: 0, key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88, nativeVirtualKeyCode: 88 });
  await key({ type: 'char', modifiers: 0, key: 'x', code: 'KeyX', text: 'x', windowsVirtualKeyCode: 88, nativeVirtualKeyCode: 88 });
  await key({ type: 'keyUp', modifiers: 0, key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88, nativeVirtualKeyCode: 88 });
  await new Promise((r) => setTimeout(r, 500));
  const r = await send('Runtime.evaluate', { expression: `JSON.stringify(window.__keys)`, returnByValue: true });
  console.log('PAGE_KEYS=' + r.result.value);
  process.exit(0);
}
main().catch((e) => { console.error('ERR ' + e.message); process.exit(1); });
