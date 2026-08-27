// v3: read chrome://downloads rendered text via shadow-DOM traversal
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
  out.title = await evalJs('document.title');
  out.bodyText = await evalJs('document.body ? document.body.innerText : ""');
  // Deep shadow-DOM text harvest
  out.shadowText = await evalJs(`(() => {
    const texts = [];
    const walk = (root, depth) => {
      if (depth > 12) return;
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const n of nodes) {
        if (n.shadowRoot) walk(n.shadowRoot, depth + 1);
        if (n.tagName && ['A','SPAN','DIV','H1','H2','H3','P','BUTTON','IMG'].includes(n.tagName)) {
          const t = (n.textContent || '').trim();
          if (t && t.length > 1 && !texts.includes(t)) texts.push(t);
        }
      }
    };
    walk(document, 0);
    if (document.documentElement.shadowRoot) walk(document.documentElement.shadowRoot, 0);
    return JSON.stringify(texts.slice(0, 200));
  })()`);
  out.htmlSnippet = await evalJs(`(() => {
    const s = document.documentElement.outerHTML;
    const idx = s.search(/google|tor-0\.4\.8|From/i);
    return idx === -1 ? 'NO_MATCH' : s.slice(Math.max(0, idx - 300), idx + 300);
  })()`);

  console.log(JSON.stringify(out, null, 2));
  fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 2));
  ws.close();
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
