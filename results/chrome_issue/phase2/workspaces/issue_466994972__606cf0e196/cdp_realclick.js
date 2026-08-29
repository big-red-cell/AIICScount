// v7: real mouse click (user activation) on the Google redirect page link, then read download UI origin
const fs = require('fs');
const PORT = 9222;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const out = { steps: [] };
  const record = (name, data) => { out.steps.push({ name, ...data }); console.log(`[${name}]`, JSON.stringify(data)); };

  const res = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' });
  const tab = await res.json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let msgId = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  };
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evalJs = async (expression, retries = 3) => {
    for (let i = 0; i < retries; i++) {
      try {
        const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
        if (r.exceptionDetails) throw new Error('Eval exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
        return r.result ? r.result.value : undefined;
      } catch (e) {
        if (String(e).includes('navigated or closed') && i < retries - 1) { await sleep(2500); continue; }
        throw e;
      }
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Input.setIgnoreInputEvents', { ignore: false });

  const target = 'https://www.google.com/url?q=https://dist.torproject.org/tor-0.4.8.21.tar.gz';
  await send('Page.navigate', { url: target });
  await sleep(8000);
  record('navigate-google', { url: await evalJs('location.href'), title: await evalJs('document.title') });

  // get anchor rect
  const rect = JSON.parse(await evalJs(`(() => {
    const a = Array.from(document.querySelectorAll('a')).find(x => x.textContent && x.textContent.indexOf('torproject.org') !== -1);
    if (!a) return null;
    const r = a.getBoundingClientRect();
    return JSON.stringify({ x: r.x + r.width / 2, y: r.y + r.height / 2, href: a.href, text: a.textContent.trim().slice(0, 80) });
  })()`));
  record('anchor-rect', rect);

  // real mouse click
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rect.x, y: rect.y });
  await sleep(300);
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: rect.x, y: rect.y, button: 'left', clickCount: 1 });
  await sleep(200);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: rect.x, y: rect.y, button: 'left', clickCount: 1 });
  record('mouse-click-dispatched', { x: rect.x, y: rect.y });

  await sleep(15000);
  record('after-click-tab', { url: await evalJs('location.href') });

  // read chrome://downloads item origin
  await send('Page.navigate', { url: 'chrome://downloads' });
  await sleep(5000);
  const item = await evalJs(`(() => {
    let found = null;
    const find = (root, depth) => {
      if (depth > 20 || found) return;
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const n of all) {
        if (n.localName && n.localName.includes('downloads-item')) { found = n; return; }
        if (n.shadowRoot) find(n.shadowRoot, depth + 1);
      }
    };
    find(document, 0);
    if (!found) return 'NO_ITEM';
    const sh = found.shadowRoot || found;
    const io = sh.querySelector('#initiator-origin');
    const fileLink = sh.querySelector('#fileLink');
    return JSON.stringify({
      initiatorOriginText: io ? io.textContent.trim() : 'NO_ELEMENT',
      initiatorOriginHtml: io ? io.innerHTML : '',
      fileLinkHref: fileLink ? fileLink.href : null,
      allDescriptions: Array.from(sh.querySelectorAll('.description')).map(d => ({ hidden: d.hasAttribute('hidden'), text: d.textContent.trim() })),
    });
  })()`);
  record('downloads-item', JSON.parse(item));

  console.log(JSON.stringify(out, null, 2));
  fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 2));
  ws.close();
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
