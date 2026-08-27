import { appendFileSync, readFileSync, existsSync } from 'fs';
import { get as httpGet, request as httpRequest } from 'http';

const LOG = 'D:\\Codes\\agents\\aiic_three_stage_pipeline\\artifacts\\reproduction\\repro\\issue_385263984__060d45f1a9\\cdp_flow3.log';
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
  const list = await getJSON('http://127.0.0.1:9222/json/list');
  const tab = list.find(t => t.type === 'page');
  log('reusing tab: ' + tab.id);
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');

  // A: chrome://chrome-urls, click the exact "Enable internal debugging pages" cr-button
  await cdp.send('Page.navigate', { url: 'chrome://chrome-urls/' });
  log('A. navigate chrome-urls -> ' + await cdp.waitLoad(20000));

  const clickRes = await cdp.eval(`(() => {
    const walk = (root, fn) => { root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot, fn); }); fn(root); };
    let target = null;
    walk(document, (root) => {
      if (target) return;
      const cands = [...root.querySelectorAll('cr-button, button')];
      target = cands.find(el => (el.textContent || '').trim() === 'Enable internal debugging pages')
            || cands.find(el => /enable internal debugging/i.test(el.textContent || ''));
    });
    if (!target) return { found: false };
    const r = target.getBoundingClientRect();
    const info = { found: true, tag: target.tagName, text: (target.textContent || '').trim().slice(0, 80), rect: { x: r.x + r.width / 2, y: r.y + r.height / 2 }, disabled: target.disabled === true };
    target.click();
    return info;
  })()`);
  log('A1. click result: ' + JSON.stringify(clickRes));
  await sleep(3000);
  // read state change if any (button may now show different text / be hidden)
  const after = await cdp.eval(`(() => {
    const out = { url: location.href };
    const walk = (root) => {
      root.querySelectorAll('cr-button, button').forEach(el => out.btns = (out.btns || []).concat((el.textContent || '').trim().slice(0, 60)));
      root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
    };
    walk(document);
    return out;
  })()`);
  log('A2. after click: ' + JSON.stringify(after));

  // B: try download-internals again
  await cdp.send('Page.navigate', { url: 'chrome://download-internals/' });
  const sb = await cdp.waitLoad(20000);
  log('B. navigate download-internals -> ' + sb);

  const text = await cdp.eval('document.body.innerText').catch(e => 'ERR:' + e);
  log('B1. page text (first 600): ' + JSON.stringify((text || '').slice(0, 600)));

  const controls = await cdp.eval(`(() => {
    const out = [];
    const walk = (root) => {
      root.querySelectorAll('input, button').forEach(el => out.push({tag: el.tagName, type: el.type||'', id: el.id||'', placeholder: el.placeholder||'', text: (el.textContent||'').trim().slice(0,60)}));
      root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
    };
    walk(document);
    return out;
  })()`);
  log('B2. controls: ' + JSON.stringify(controls));

  if (!sb.includes('debug-webuis-disabled')) {
    // C: fill URL + click Download
    await marker('before-download-click-3');
    const clickRes2 = await cdp.eval(`(() => {
      const walk = (root, fn) => { root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot, fn); }); fn(root); };
      let input = null, button = null;
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
        out.rect = { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        out.buttonText = (button.textContent || '').trim();
        button.click();
      }
      return out;
    })()`);
    log('C. fill+click -> ' + JSON.stringify(clickRes2));
    await sleep(6000);
    await marker('after-download-wait-3');
    const pageText2 = await cdp.eval('document.body.innerText').catch(e => 'ERR:' + e);
    log('C1. page text after click (first 2500): ' + JSON.stringify((pageText2 || '').slice(0, 2500)));
    log('C2. active URL: ' + await cdp.eval('location.href'));

    const reqLogBefore = readReqLog();
    const hitsBefore = (reqLogBefore.match(/"\/cookies"/g) || []).length;
    if (clickRes2.rect && hitsBefore <= 2) {
      log('C3. no new /cookies request; real mouse click at ' + JSON.stringify(clickRes2.rect));
      await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: clickRes2.rect.x, y: clickRes2.rect.y, button: 'left', clickCount: 1 });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: clickRes2.rect.x, y: clickRes2.rect.y, button: 'left', clickCount: 1 });
      await sleep(6000);
      await marker('after-mouse-click-3');
    }
  } else {
    log('C. SKIPPED: download-internals still disabled');
  }

  log('===== REQUESTS LOG (tail) =====');
  const lines = readReqLog().trim().split('\n');
  log(lines.slice(-12).join('\n'));
  process.exit(0);
}

main().catch(e => { log('FATAL: ' + (e && e.stack ? e.stack : e)); process.exit(1); });
