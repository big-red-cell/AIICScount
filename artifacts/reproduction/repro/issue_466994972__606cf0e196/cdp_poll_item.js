// v6: wait for scan to complete, then read initiator-origin + full item state
const fs = require('fs');
const PORT = 9222;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const out = {};
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
  await send('Page.navigate', { url: 'chrome://downloads' });
  await sleep(3000);

  const grab = async () => {
    const itemHtml = await evalJs(`(() => {
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
      const desc = sh.querySelector('.description[hidden=""], .description:not([hidden])');
      return JSON.stringify({
        initiatorOriginText: io ? io.textContent.trim() : 'NO_ELEMENT',
        initiatorOriginHtml: io ? io.innerHTML : '',
        allDescriptions: Array.from(sh.querySelectorAll('.description')).map(d => ({ hidden: d.hasAttribute('hidden'), text: d.textContent.trim() })),
        danger: found.getAttribute('data-danger-type'),
      });
    })()`);
    return JSON.parse(itemHtml);
  };

  const samples = [];
  for (let i = 0; i < 8; i++) {
    await sleep(5000);
    try { samples.push(await grab()); } catch (e) { samples.push({ error: String(e).slice(0, 200) }); }
  }
  out.samples = samples;
  console.log(JSON.stringify(out, null, 2));
  fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 2));
  ws.close();
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
