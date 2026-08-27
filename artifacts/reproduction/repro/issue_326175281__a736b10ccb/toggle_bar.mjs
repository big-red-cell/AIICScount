// Toggle bookmarks bar with corrected modifier semantics and verify via innerHeight
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
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id) { const p = pending.get(msg.id); if (p) { pending.delete(msg.id); msg.error ? p.rej(new Error(JSON.stringify(msg.error))) : p.res(msg.result); } }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id; pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const key = async (params) => { await send('Input.dispatchKeyEvent', params); };

  const evalH = async () => {
    const r = await send('Runtime.evaluate', { expression: 'window.innerHeight', returnByValue: true });
    return r.result.value;
  };
  await send('Runtime.enable');
  console.log('INNER_H_BEFORE=' + await evalH());

  // Ctrl+Shift+B with correct modifier state semantics
  await key({ type: 'rawKeyDown', modifiers: 0, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17 });
  await key({ type: 'rawKeyDown', modifiers: 2, key: 'Shift', code: 'ShiftLeft', windowsVirtualKeyCode: 16, nativeVirtualKeyCode: 16 });
  await key({ type: 'rawKeyDown', modifiers: 3, key: 'B', code: 'KeyB', windowsVirtualKeyCode: 66, nativeVirtualKeyCode: 66 });
  await key({ type: 'keyUp', modifiers: 3, key: 'B', code: 'KeyB', windowsVirtualKeyCode: 66, nativeVirtualKeyCode: 66 });
  await key({ type: 'keyUp', modifiers: 2, key: 'Shift', code: 'ShiftLeft', windowsVirtualKeyCode: 16, nativeVirtualKeyCode: 16 });
  await key({ type: 'keyUp', modifiers: 0, key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, nativeVirtualKeyCode: 17 });
  await new Promise((r) => setTimeout(r, 2000));
  console.log('INNER_H_AFTER=' + await evalH());
  process.exit(0);
}
main().catch((e) => { console.error('ERR ' + e.message); process.exit(1); });
