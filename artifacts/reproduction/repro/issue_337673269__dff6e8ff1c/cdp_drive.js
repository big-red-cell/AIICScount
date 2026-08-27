// CDP driver: navigate to credential URL, read back tab state, Ctrl+D bookmark.
const http = require('http');

function getJSON(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const targets = await getJSON('http://127.0.0.1:9222/json/list');
  const page = targets.find((t) => t.type === 'page');
  if (!page) throw new Error('no page target');
  console.log('TARGET_URL:', page.url);

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let msgId = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const mid = ++msgId;
      pending.set(mid, resolve);
      ws.send(JSON.stringify({ id: mid, method, params }));
    });

  await send('Page.enable');
  await send('Runtime.enable');

  // Step 1: navigate to the issue URL (credentials embedded)
  await send('Page.navigate', { url: 'https://1:1@httpbin.org/basic-auth/1/1' });
  await sleep(5000);

  const loc = await send('Runtime.evaluate', { expression: 'location.href', returnByValue: true });
  console.log('LOCATION_AFTER_NAV:', JSON.stringify(loc.result.result.value));

  const body = await send('Runtime.evaluate', {
    expression: 'document.body ? document.body.innerText.slice(0, 300) : "(no body)"',
    returnByValue: true,
  });
  console.log('BODY_SNIPPET:', JSON.stringify(body.result.result.value));

  // Step 2: bookmark current tab via Ctrl+D
  const mod = 2; // Ctrl
  await send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: mod, key: 'd', code: 'KeyD', windowsVirtualKeyCode: 68, nativeVirtualKeyCode: 68 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: mod, key: 'd', code: 'KeyD', windowsVirtualKeyCode: 68, nativeVirtualKeyCode: 68 });
  await sleep(2000);

  // Confirm the bookmark dialog with Enter (Done is the default button)
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await sleep(2500);

  // Read back tab state again
  const loc2 = await send('Runtime.evaluate', { expression: 'location.href', returnByValue: true });
  console.log('LOCATION_AFTER_BOOKMARK:', JSON.stringify(loc2.result.result.value));

  ws.close();
  process.exit(0);
}

main().catch((e) => { console.error('DRIVER_ERR', e); process.exit(1); });
