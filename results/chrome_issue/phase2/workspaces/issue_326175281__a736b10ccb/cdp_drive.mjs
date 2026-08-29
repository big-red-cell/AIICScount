// CDP driver for issue 326175281 reproduction (javascript: bookmark execution)
// Modes:
//   info <url>            -> navigate to <url>, print browser/window/rect info as JSON
//   target <url> <shot>   -> navigate, set cookie, wait for JS dialog (45s), accept, screenshot
//   eval <expr>           -> evaluate expression, print result value
import fs from 'node:fs';

const PORT = 9222;
const BASE = `http://127.0.0.1:${PORT}`;
const mode = process.argv[2];
const arg1 = process.argv[3];
const arg2 = process.argv[4];

async function getTargets() {
  const res = await fetch(`${BASE}/json/list`);
  return res.json();
}

async function connect() {
  const targets = await getTargets();
  const t = targets.find((x) => x.type === 'page');
  if (!t) throw new Error('no page target: ' + JSON.stringify(targets.map((x) => x.type)));
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id) {
      const p = pending.get(msg.id);
      if (p) { pending.delete(msg.id); msg.error ? p.rej(new Error(JSON.stringify(msg.error))) : p.res(msg.result); }
    } else if (msg.method) {
      for (const l of listeners) l(msg);
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const onEvent = (fn) => listeners.add(fn);
  const offEvent = (fn) => listeners.delete(fn);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const waitLoad = async (timeoutMs = 15000) => {
    return new Promise((res, rej) => {
      const timer = setTimeout(() => { offEvent(h); rej(new Error('load timeout')); }, timeoutMs);
      const h = (m) => { if (m.method === 'Page.loadEventFired') { clearTimeout(timer); offEvent(h); res(); } };
      onEvent(h);
    });
  };
  return { ws, send, onEvent, offEvent, sleep, evalJs, waitLoad };
}

async function info(url) {
  const c = await connect();
  const ver = await c.send('Browser.getVersion');
  const win = await c.send('Browser.getWindowForTarget');
  await c.send('Page.enable');
  await c.send('Runtime.enable');
  const loadP = c.waitLoad();
  await c.send('Page.navigate', { url });
  await loadP;
  // wait for the image to be laid out
  for (let i = 0; i < 20; i++) {
    const done = await c.evalJs(`document.images.length > 0 && document.images[0].complete`);
    if (done) break;
    await c.sleep(250);
  }
  await c.sleep(500);
  const geo = await c.evalJs(`(() => {
    const r = document.querySelector('a#lure img').getBoundingClientRect();
    return { sx: window.screenX, sy: window.screenY,
             ox: window.outerWidth, oy: window.outerHeight,
             ix: window.innerWidth, iy: window.innerHeight,
             rect: { x: r.x, y: r.y, w: r.width, h: r.height },
             href: document.querySelector('a#lure').href,
             url: location.href, title: document.title };
  })()`);
  const out = { browser: ver.product, version: ver.browserVersion,
                bounds: win.bounds, page: geo };
  console.log('INFO=' + JSON.stringify(out));
  process.exit(0);
}

async function target(url, shotPath) {
  const c = await connect();
  await c.send('Page.enable');
  await c.send('Runtime.enable');
  const loadP = c.waitLoad();
  await c.send('Page.navigate', { url });
  await loadP;
  await c.sleep(400);
  const cookie = await c.evalJs(`document.cookie = "session=TOPSECRET123; path=/"; document.cookie`);
  console.log('COOKIE_AFTER_SET=' + cookie);
  const page = await c.evalJs(`location.href + ' | ' + document.title`);
  console.log('PAGE=' + page);
  console.log('READY');
  const dialogP = new Promise((res) => {
    c.onEvent((m) => { if (m.method === 'Page.javascriptDialogOpening') res(m.params); });
  });
  const timeoutP = new Promise((res) => setTimeout(() => res(null), 45000));
  const dlg = await Promise.race([dialogP, timeoutP]);
  if (dlg) {
    console.log('DIALOG=' + JSON.stringify(dlg));
    await c.send('Page.handleJavaScriptDialog', { accept: true });
    await c.sleep(400);
    const shot = await c.send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
    console.log('SCREENSHOT_SAVED=' + shotPath + ' size=' + fs.statSync(shotPath).size);
  } else {
    console.log('NO_DIALOG_TIMEOUT');
  }
  process.exit(0);
}

async function evalMode(expr) {
  const c = await connect();
  await c.send('Runtime.enable');
  const v = await c.evalJs(expr);
  console.log('EVAL=' + JSON.stringify(v));
  process.exit(0);
}

await (async () => {
  if (mode === 'info') return info(arg1);
  if (mode === 'target') return target(arg1, arg2);
  if (mode === 'eval') return evalMode(arg1);
  throw new Error('unknown mode ' + mode);
})();
