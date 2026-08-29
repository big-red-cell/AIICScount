// Test whether CDP Input.dispatchKeyEvent triggers browser-level shortcuts
// 1) Ctrl+T -> new tab should appear (target count increases)
// 2) Ctrl+Shift+B -> bookmark bar preference should flip to true
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
  const key = async (name, code, vk, mods = 0, type = 'rawKeyDown') => {
    await send('Input.dispatchKeyEvent', { type, key: name, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers: mods });
  };
  const before = (await getTargets()).filter((x) => x.type === 'page').length;
  console.log('TABS_BEFORE=' + before);

  // Ctrl+T
  await key('t', 'KeyT', 84, 2, 'rawKeyDown');
  await key('t', 'KeyT', 84, 2, 'keyUp');
  await key('Control', 'ControlLeft', 17, 0, 'keyUp');
  await new Promise((r) => setTimeout(r, 1500));
  const after = (await getTargets()).filter((x) => x.type === 'page').length;
  console.log('TABS_AFTER_CTRL_T=' + after);

  // Ctrl+Shift+B
  await key('Control', 'ControlLeft', 17, 2, 'rawKeyDown');
  await key('Shift', 'ShiftLeft', 16, 3, 'rawKeyDown');
  await key('B', 'KeyB', 66, 3, 'rawKeyDown');
  await key('B', 'KeyB', 66, 3, 'keyUp');
  await key('Shift', 'ShiftLeft', 16, 2, 'keyUp');
  await key('Control', 'ControlLeft', 17, 0, 'keyUp');
  await new Promise((r) => setTimeout(r, 1500));
  console.log('CTRL_SHIFT_B_SENT');
  process.exit(0);
}
main().catch((e) => { console.error('ERR ' + e.message); process.exit(1); });
