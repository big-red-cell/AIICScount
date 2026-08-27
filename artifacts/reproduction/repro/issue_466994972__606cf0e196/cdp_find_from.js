// v4: locate the "From" / site-URL element inside chrome://downloads shadow DOM
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
  await sleep(8000);

  out.url = await evalJs('location.href');

  // Collect every element (across shadow roots) whose text or attributes mention google / tor / 来自 / from
  out.hits = JSON.parse(await evalJs(`(() => {
    const hits = [];
    const seen = new Set();
    const walk = (root, depth) => {
      if (depth > 20) return;
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const n of all) {
        if (n.shadowRoot) walk(n.shadowRoot, depth + 1);
        const t = (n.textContent || '').trim();
        const attrs = Array.from(n.attributes || []).map(a => a.name + '=' + a.value).join(' ');
        const hay = (n.tagName + ' ' + attrs + ' ' + t).toLowerCase();
        if (/google|tor-0\.4\.8|来自|from/i.test(hay)) {
          const key = n.tagName + '|' + t.slice(0, 80) + '|' + attrs.slice(0, 120);
          if (!seen.has(key)) {
            seen.add(key);
            hits.push({ tag: n.tagName, text: t.slice(0, 200), attrs: attrs.slice(0, 250), href: n.href || null });
          }
        }
      }
    };
    walk(document, 0);
    return JSON.stringify(hits.slice(0, 60));
  })()`));

  console.log(JSON.stringify(out, null, 2));
  fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 2));
  ws.close();
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
