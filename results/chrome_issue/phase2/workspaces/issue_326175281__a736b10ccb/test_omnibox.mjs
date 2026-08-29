// Test: CDP Ctrl+L focuses omnibox? Probe: page keydown listener should NOT see 'x' if omnibox gets it.
const PORT = 9222;
const BASE = `http://127.0.0.1:${PORT}`;

async function getTargets() {
  const res = await fetch(`${BASE}/json/list`);
  return res.json();
}

async function main() {
  const targets = await getTargets();
  const t = targets.find((x) => x.type === 'page' && x.title.includes('Anti-bot'));
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
  await send('Runtime.evaluate', { expression: `window.__keys = []; window.addEventListener('keydown', (e) => window.__keys.push(e.key)); 'ok'` });
  await new Promise((r) => setTimeout(r, 300));

  // Ctrl+L
  await key({ type: 'rawKeyDown', modifiers: 0, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17 });
  await key({ type: 'rawKeyDown', modifiers: 2, key: 'l', code: 'KeyL', windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });
  await key({ type: 'keyUp', modifiers: 2, key: 'l', code: 'KeyL', windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });
  await key({ type: 'keyUp', modifiers: 0, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17 });
  await new Promise((r) => setTimeout(r, 800));

  // type 'x' (char sequence)
  await key({ type: 'rawKeyDown', modifiers: 0, key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88, nativeVirtualKeyCode: 88 });
  await key({ type: 'char', modifiers: 0, key: 'x', code: 'KeyX', text: 'x', unmodifiedText: 'x', windowsVirtualKeyCode: 88, nativeVirtualKeyCode: 88 });
  await key({ type: 'keyUp', modifiers: 0, key: 'x', code: 'KeyX', windowsVirtualKeyCode: 88, nativeVirtualKeyCode: 88 });
  await new Promise((r) => setTimeout(r, 600));
  const r = await send('Runtime.evaluate', { expression: `JSON.stringify(window.__keys)`, returnByValue: true });
  console.log('PAGE_KEYS_AFTER_CTRL_L=' + r.result.value);
  process.exit(0);
}
main().catch((e) => { console.error('ERR ' + e.message); process.exit(1); });
