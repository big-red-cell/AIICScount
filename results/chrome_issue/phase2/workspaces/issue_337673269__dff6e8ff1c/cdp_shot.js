// Capture a screenshot of the current page target via CDP.
async function main() {
  const res = await fetch('http://127.0.0.1:9222/json/list');
  const list = await res.json();
  const page = list.find(t => t.type === 'page');
  if (!page) throw new Error('no page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    }
  };
  await new Promise((res2, rej) => { ws.onopen = res2; ws.onerror = rej; });
  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const mid = ++id;
      pending.set(mid, { resolve, reject });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  }
  const out = process.argv[2];
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  const { writeFileSync } = require('fs');
  writeFileSync(out, Buffer.from(shot.data, 'base64'));
  console.log('SAVED: ' + out + ' (' + Buffer.from(shot.data, 'base64').length + ' bytes)');
  ws.close();
}
main().catch(e => { console.error('ERROR: ' + e.message); process.exit(1); });
