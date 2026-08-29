// CDP driver for issue 440868608__73cee68214 reproduction
// Modes: save | fill
const mode = process.argv[2];
const CDP_HTTP = 'http://127.0.0.1:9222';
const SITE = 'http://127.0.0.1:8123';
const PASS = 'ReproSecret_440868608';
const USER = 'repro_user';

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let seq = 0;
    const pending = new Map();
    ws.onopen = () => resolve({
      ws,
      send(method, params = {}) {
        return new Promise((res) => {
          const id = ++seq;
          pending.set(id, res);
          ws.send(JSON.stringify({ id, method, params }));
        });
      }
    });
    ws.onerror = (e) => reject(new Error('ws error ' + e.message));
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    };
  });
}

async function newTarget(url) {
  const r = await fetch(`${CDP_HTTP}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' });
  return r.json();
}

async function listTargets() {
  const r = await fetch(`${CDP_HTTP}/json/list`);
  return r.json();
}

async function evalJS(cdp, expression) {
  const m = await cdp.send('Runtime.evaluate', {
    expression, returnByValue: true, awaitPromise: true
  });
  if (m.error) throw new Error('CDP error: ' + JSON.stringify(m.error));
  if (m.result && m.result.exceptionDetails) {
    return { exception: m.result.exceptionDetails.exception?.description || m.result.exceptionDetails.text };
  }
  return { value: m.result?.result?.value };
}

async function waitReady(cdp, timeoutMs = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const r = await evalJS(cdp, 'document.readyState');
    if (r.value === 'complete') return true;
    await new Promise((res) => setTimeout(res, 200));
  }
  return false;
}

if (mode === 'save') {
  const t = await newTarget('chrome://password-manager/passwords');
  console.log('TARGET_CREATED ' + JSON.stringify({ id: t.id, url: t.url }));
  const cdp = await connect(t.webSocketDebuggerUrl);
  await cdp.send('Runtime.enable');
  await waitReady(cdp);
  await new Promise((res) => setTimeout(res, 800));

  const introspect = await evalJS(cdp,
    `(() => { const c = (typeof chrome !== 'undefined' && chrome.passwordManagerPrivate) ? chrome.passwordManagerPrivate : null;
       return { hasApi: !!c, keys: c ? Object.keys(c).sort() : [] }; })()`);
  console.log('INTROSPECT ' + JSON.stringify(introspect));

  const addResult = await evalJS(cdp, `(async () => {
    const c = chrome.passwordManagerPrivate;
    const url = ${JSON.stringify(SITE)};
    const username = ${JSON.stringify(USER)};
    const password = ${JSON.stringify(PASS)};
    const attempts = [];
    const shapes = [
      { entry: { url, username, password, note: '' } },
      { origin: url, username, password },
      { url, username, password }
    ];
    for (const shape of shapes) {
      try { await c.addPassword(shape); attempts.push({ shape: Object.keys(shape), ok: true }); break; }
      catch (e) { attempts.push({ shape: Object.keys(shape), ok: false, err: String(e) }); }
    }
    return { attempts };
  })()`);
  console.log('ADDPASSWORD ' + JSON.stringify(addResult));

  await new Promise((res) => setTimeout(res, 500));
  const list = await evalJS(cdp, `(async () => {
    const c = chrome.passwordManagerPrivate;
    try {
      const entries = await c.getSavedPasswordList();
      return entries.map(e => ({ id: e.id, url: e.url, username: e.username, hasPasswordField: 'password' in e }));
    } catch (e) { return { err: String(e) }; }
  })()`);
  console.log('SAVEDLIST ' + JSON.stringify(list));
  process.exit(0);
}

if (mode === 'fill') {
  let targets = await listTargets();
  let t = targets.find((x) => x.type === 'page' && x.url.startsWith(SITE));
  if (!t) {
    t = await newTarget(SITE + '/login.html');
    await new Promise((res) => setTimeout(res, 800));
  }
  const cdp = await connect(t.webSocketDebuggerUrl);
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  await cdp.send('Page.navigate', { url: SITE + '/login.html' });
  await waitReady(cdp);
  await new Promise((res) => setTimeout(res, 600));

  const coords = await evalJS(cdp, `(() => {
    const el = document.getElementById('user');
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), w: r.width, h: r.height };
  })()`);
  console.log('FIELD_COORDS ' + JSON.stringify(coords));

  // real mouse click on username field to trigger autofill dropdown
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: coords.value.x, y: coords.value.y });
  await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: coords.value.x, y: coords.value.y, button: 'left', clickCount: 1 });
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: coords.value.x, y: coords.value.y, button: 'left', clickCount: 1 });
  await new Promise((res) => setTimeout(res, 700));

  const before = await evalJS(cdp, `(() => {
    const u = document.getElementById('user'), p = document.getElementById('pass');
    return { user: u.value, pass: p.value, active: document.activeElement ? document.activeElement.id : null };
  })()`);
  console.log('AFTER_CLICK ' + JSON.stringify(before));

  // keyboard selection of the first autofill suggestion
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 });
  await new Promise((res) => setTimeout(res, 250));
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
  await new Promise((res) => setTimeout(res, 700));

  const after = await evalJS(cdp, `(() => {
    const u = document.getElementById('user'), p = document.getElementById('pass');
    return { user: u.value, passType: p.type, passBeforeUnmask: p.value };
  })()`);
  console.log('AFTER_AUTOFILL ' + JSON.stringify(after));

  const unmask = await evalJS(cdp, `(() => {
    const p = document.getElementById('pass');
    p.type = 'text';  // issue's method: change HTML type password -> text
    return { passTypeNow: p.type, passValueAfterTypeChange: p.value };
  })()`);
  console.log('UNMASK ' + JSON.stringify(unmask));
  process.exit(0);
}

console.log('unknown mode');
process.exit(2);
