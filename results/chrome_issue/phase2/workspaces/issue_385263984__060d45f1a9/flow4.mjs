import { appendFileSync, readFileSync, existsSync } from 'fs';
import { get as httpGet, request as httpRequest } from 'http';

const LOG = 'D:\\Codes\\agents\\aiic_three_stage_pipeline\\artifacts\\reproduction\\repro\\issue_385263984__060d45f1a9\\cdp_flow4.log';
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
  await cdp.send('Network.enable');

  // confirm cookie still present in the browser cookie store
  const cookies = await cdp.send('Network.getAllCookies');
  const ourCookies = cookies.cookies.filter(c => c.name === 'test');
  log('0. cookies named test in store: ' + JSON.stringify(ourCookies));

  // navigate to download-internals
  await cdp.send('Page.navigate', { url: 'chrome://download-internals/' });
  log('A. navigate -> ' + await cdp.waitLoad(20000));

  // fill the URL input (type=url) and verify value readback
  const fillRes = await cdp.eval(`(() => {
    const input = document.querySelector('#download-url');
    if (!input) return { found: false };
    input.value = 'http://127.0.0.1:18080/cookies';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return { found: true, valueAfter: input.value, type: input.type };
  })()`);
  log('B. fill input -> ' + JSON.stringify(fillRes));
  await sleep(300);

  // click the Download button
  await marker('before-download-click-4');
  const btnRes = await cdp.eval(`(() => {
    const b = document.querySelector('#start-download');
    if (!b) return { found: false };
    const r = b.getBoundingClientRect();
    b.click();
    return { found: true, rect: { x: r.x + r.width / 2, y: r.y + r.height / 2 }, text: b.textContent.trim() };
  })()`);
  log('C. click download -> ' + JSON.stringify(btnRes));
  await sleep(6000);
  await marker('after-download-wait-4');

  // readback: entry requests section of the page
  const pageText = await cdp.eval('document.body.innerText').catch(e => 'ERR:' + e);
  const idx = (pageText || '').indexOf('Entry Requests');
  log('D. page text from "Entry Requests" (first 1200): ' + JSON.stringify((pageText || '').slice(idx, idx + 1200)));

  // full requests log tail
  const lines = readReqLog().trim().split('\n');
  const idx2 = lines.findIndex(l => l.includes('before-download-click-4'));
  log('===== REQUESTS LOG from before-download-click-4 =====');
  log(lines.slice(idx2).join('\n'));
  process.exit(0);
}

main().catch(e => { log('FATAL: ' + (e && e.stack ? e.stack : e)); process.exit(1); });
