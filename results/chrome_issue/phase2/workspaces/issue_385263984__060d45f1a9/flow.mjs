import { appendFileSync, readFileSync, existsSync } from 'fs';
import { get as httpGet, request as httpRequest } from 'http';

const LOG = 'D:\\Codes\\agents\\aiic_three_stage_pipeline\\artifacts\\reproduction\\repro\\issue_385263984__060d45f1a9\\cdp_flow.log';
const REQLOG = 'D:\\Codes\\agents\\aiic_three_stage_pipeline\\artifacts\\reproduction\\repro\\issue_385263984__060d45f1a9\\requests.log';
const log = (s) => { const line = `[${new Date().toISOString()}] ${s}`; appendFileSync(LOG, line + '\n'); console.log(line); };

const getJSON = (url) => new Promise((res, rej) => {
  httpGet(url, (r) => { let d = ''; r.on('data', c => d += c); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } }); }).on('error', rej);
});

function marker(step) {
  return new Promise((res) => {
    const req = httpRequest('http://127.0.0.1:18080/marker?step=' + encodeURIComponent(step), (r) => { r.resume(); r.on('end', res); });
    req.on('error', () => res());
    req.end();
  });
}

class CDP {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.id = 0; this.pending = new Map(); }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = () => rej(new Error('ws connect error')); });
    this.ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails));
    return r.result ? r.result.value : undefined;
  }
  async waitLoad(timeoutMs = 15000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      const st = await this.eval('document.readyState + "|" + location.href').catch(() => 'err');
      if (st && st.startsWith('complete|')) return st;
      await new Promise(r => setTimeout(r, 250));
    }
    return 'TIMEOUT|' + (await this.eval('document.readyState + "|" + location.href').catch(() => 'err'));
  }
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const readReqLog = () => existsSync(REQLOG) ? readFileSync(REQLOG, 'utf8') : '(no log)';

async function main() {
  // create a fresh tab
  let tab;
  try {
    tab = await getJSON('http://127.0.0.1:9222/json/new?about:blank');
  } catch (e) {
    const list = await getJSON('http://127.0.0.1:9222/json/list');
    tab = list.find(t => t.type === 'page');
    log('json/new failed, reusing existing page target');
  }
  log('tab: id=' + tab.id + ' ws=' + tab.webSocketDebuggerUrl);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  // Step 1: set SameSite=Strict cookie for 127.0.0.1:18080
  await cdp.send('Page.navigate', { url: 'http://127.0.0.1:18080/set' });
  const s1 = await cdp.waitLoad();
  log('1. navigate /set -> ' + s1);
  const cookie = await cdp.eval('document.cookie');
  log('1v. document.cookie = ' + JSON.stringify(cookie));

  // Step 2: same-site fetch control (cookie SHOULD be sent)
  await marker('before-same-site-fetch');
  const fetchRes = await cdp.eval("fetch('/cookies', {credentials:'include'}).then(async r => r.status + '|' + await r.text())");
  log('2. same-site fetch /cookies -> ' + JSON.stringify(fetchRes));
  await sleep(800);

  // Step 3: cross-site subresource control (cookie should NOT be sent)
  await cdp.send('Page.navigate', { url: 'http://127.0.0.2:18080/xsite' });
  const s3 = await cdp.waitLoad();
  log('3. navigate /xsite on 127.0.0.2 -> ' + s3);
  await sleep(2000);
  log('3v. active URL: ' + await cdp.eval('location.href'));

  // Step 4: chrome://download-internals
  await cdp.send('Page.navigate', { url: 'chrome://download-internals/' });
  const s4 = await cdp.waitLoad(20000);
  log('4. navigate download-internals -> ' + s4);

  const controls = await cdp.eval(`(() => {
    const out = [];
    const walk = (root) => {
      root.querySelectorAll('input, button').forEach(el => out.push({tag: el.tagName, type: el.type||'', id: el.id||'', placeholder: el.placeholder||'', text: (el.textContent||'').trim().slice(0,60)}));
      root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
    };
    walk(document);
    return out;
  })()`);
  log('4v. controls: ' + JSON.stringify(controls));

  // Step 5: fill URL, click Download, then verify
  await marker('before-download-click');
  const clickRes = await cdp.eval(`(() => {
    const walk = (root, fn) => { root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot, fn); }); fn(root); };
    let input = null, button = null, rect = null;
    walk(document, (root) => {
      if (!input) input = root.querySelector('input[type="text"], input:not([type])');
      if (!button) button = [...root.querySelectorAll('button')].find(b => /download/i.test(b.textContent || ''));
    });
    const out = { inputFound: !!input, buttonFound: !!button };
    if (input) {
      input.value = 'http://127.0.0.1:18080/cookies';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      out.inputValueAfter = input.value;
    }
    if (button) {
      const r = button.getBoundingClientRect();
      rect = { x: r.x + r.width / 2, y: r.y + r.height / 2 };
      out.buttonText = (button.textContent || '').trim();
      button.click();
      out.rect = rect;
    }
    return out;
  })()`);
  log('5. fill+click -> ' + JSON.stringify(clickRes));

  await sleep(6000);
  await marker('after-download-wait');

  const pageText = await cdp.eval('document.body.innerText').catch(e => 'ERR:' + e);
  log('5v. page innerText (first 1500): ' + JSON.stringify((pageText || '').slice(0, 1500)));
  log('5v. active URL: ' + await cdp.eval('location.href'));

  // fallback: if no download request observed yet, try real mouse click on the button
  const reqLogBefore = readReqLog();
  const downloadHitsBefore = (reqLogBefore.match(/"\/cookies"/g) || []).length;
  if (clickRes.rect && downloadHitsBefore <= 1) {
    log('5f. no new download request seen; trying Input.dispatchMouseEvent at ' + JSON.stringify(clickRes.rect));
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: clickRes.rect.x, y: clickRes.rect.y, button: 'left', clickCount: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: clickRes.rect.x, y: clickRes.rect.y, button: 'left', clickCount: 1 });
    await sleep(5000);
    await marker('after-mouse-click-fallback');
  }

  log('===== REQUESTS LOG =====');
  log(readReqLog());
  process.exit(0);
}

main().catch(e => { log('FATAL: ' + (e && e.stack ? e.stack : e)); process.exit(1); });
