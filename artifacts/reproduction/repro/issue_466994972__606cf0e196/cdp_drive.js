// CDP driver for issue 466994972__606cf0e196 (download source spoofing via Google redirect page) - v2
const fs = require('fs');
const PORT = 9222;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const log = { steps: [], downloadsPageText: null, chromeDownloadsReached: false };
  const record = (name, data) => { log.steps.push({ name, ...data }); console.log(`[${name}]`, JSON.stringify(data)); };

  const res = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' });
  const tab = await res.json();
  record('tab-created', { id: tab.id });

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
  await new Promise((res2, rej) => { ws.onopen = res2; ws.onerror = rej; });

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
        const s = String(e);
        if (s.includes('navigated or closed') && i < retries - 1) { await sleep(2500); continue; }
        throw e;
      }
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');

  const target = 'https://www.google.com/url?q=https://dist.torproject.org/tor-0.4.8.21.tar.gz';
  await send('Page.navigate', { url: target });
  await sleep(8000);
  record('navigate-google', {
    url: await evalJs('location.href'),
    title: await evalJs('document.title'),
    origin: await evalJs('location.origin'),
  });

  const anchors = JSON.parse(await evalJs(`JSON.stringify(Array.from(document.querySelectorAll('a')).map(a => ({ text: a.textContent.trim().slice(0,100), href: a.href })))`));
  record('anchors', { anchors });

  const clicked = await evalJs(`(() => {
    const a = Array.from(document.querySelectorAll('a')).find(x => x.textContent && x.textContent.indexOf('torproject.org') !== -1);
    if (!a) return 'NO_ANCHOR';
    a.click();
    return 'CLICKED:' + a.href;
  })()`);
  record('click-download-link', { clicked });

  // wait for the download to start / navigation settle
  await sleep(12000);
  record('after-click-tab', { url: await evalJs('location.href') });

  // Navigate to chrome://downloads and read the rendered text
  try {
    await send('Page.navigate', { url: 'chrome://downloads' });
    await sleep(7000);
    const dlText = await evalJs('document.body ? document.body.innerText : ""');
    log.chromeDownloadsReached = true;
    log.downloadsPageText = dlText;
    record('downloads-page', { length: dlText ? dlText.length : 0, excerpt: dlText ? dlText.slice(0, 2000) : null });
  } catch (e) {
    record('chrome-downloads-eval-failed', { error: String(e).slice(0, 300) });
  }

  ws.close();
  fs.writeFileSync(process.argv[2], JSON.stringify(log, null, 2));
  console.log('LOG_WRITTEN');
}

main().catch((e) => { console.error('FATAL', e); process.exit(1); });
