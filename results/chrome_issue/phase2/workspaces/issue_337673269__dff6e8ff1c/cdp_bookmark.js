// CDP driver: navigate to https://1:1@httpbin.org/basic-auth/1/1, read back state,
// bookmark current tab (Ctrl+D then Enter), then report.
const TARGET_URL = 'https://1:1@httpbin.org/basic-auth/1/1';

async function getTarget() {
  const res = await fetch('http://127.0.0.1:9222/json/list');
  const list = await res.json();
  const page = list.find(t => t.type === 'page');
  if (!page) throw new Error('no page target found');
  return page;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  const target = await getTarget();
  console.log('TARGET: ' + target.url);
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const events = [];

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error)));
      else resolve(msg.result);
    } else if (msg.method) {
      events.push(msg);
    }
  };

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const mid = ++id;
      pending.set(mid, { resolve, reject });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  }

  async function evaluate(expr) {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }

  await send('Page.enable');
  await send('Runtime.enable');

  // 1. Navigate to the credentialed URL
  await send('Page.navigate', { url: TARGET_URL });

  // 2. Wait for load (poll readyState up to 30s)
  let state = '';
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    try {
      state = await evaluate('document.readyState');
    } catch (e) { /* context may be mid-navigation */ }
    if (state === 'complete') break;
  }
  console.log('READYSTATE: ' + state);

  // 3. Read back the committed URL and page content
  const href = await evaluate('location.href');
  console.log('HREF: ' + href);
  const body = await evaluate('document.body ? document.body.innerText : ""');
  console.log('BODY: ' + body.replace(/\s+/g, ' ').trim().slice(0, 300));
  const hasUserinfo = /^https:\/\/1:1@/.test(href);
  console.log('HREF_HAS_CREDENTIALS: ' + hasUserinfo);

  // 4. Bookmark current tab: Ctrl+D then Enter
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'd', code: 'KeyD', modifiers: 2, windowsVirtualKeyCode: 68, nativeVirtualKeyCode: 68 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'd', code: 'KeyD', modifiers: 2, windowsVirtualKeyCode: 68, nativeVirtualKeyCode: 68 });
  await sleep(800);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  console.log('BOOKMARK_SHORTCUT_SENT: true');
  await sleep(2000);

  // 5. Dump collected events for evidence
  const interesting = events.filter(e => ['Page.loadEventFired', 'Page.frameNavigated'].includes(e.method));
  console.log('EVENTS: ' + JSON.stringify(interesting.map(e => ({ method: e.method, params: e.params })).slice(0, 10)));

  ws.close();
}

main().then(() => process.exit(0)).catch(err => { console.error('ERROR: ' + err.message); process.exit(1); });
