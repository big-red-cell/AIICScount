// Listen on the dropme tab during the OS-level drag; capture console/dialog, then read state.
import { writeFileSync } from 'node:fs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class CDP {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.id = 0; this.pending = new Map(); this.listeners = new Map(); }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { res, rej } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      } else if (msg.method) {
        for (const fn of this.listeners.get(msg.method) || []) fn(msg.params);
      }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => { this.pending.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  on(method, fn) { if (!this.listeners.has(method)) this.listeners.set(method, []); this.listeners.get(method).push(fn); }
}

const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const tabB = list.find((t) => t.type === 'page' && t.url.includes('dropme'));
const b = new CDP(tabB.webSocketDebuggerUrl);
await b.open();
const consoleEv = [];
b.on('Runtime.consoleAPICalled', (p) => {
  const text = (p.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
  consoleEv.push(text);
  console.log('[EV] ' + text);
});
const dialogs = [];
b.on('Page.javascriptDialogOpening', (p) => { dialogs.push(p); console.log('[DIALOG] ' + p.message); });
await b.send('Page.enable');
await b.send('Runtime.enable');

const T0 = Date.now();
while (Date.now() - T0 < 14000) await sleep(200);

const evalT = async (expr) => {
  const r = await Promise.race([
    b.send('Runtime.evaluate', { expression: expr, returnByValue: true }),
    sleep(3000).then(() => ({ timedOut: true }))
  ]);
  if (r && r.timedOut) return 'EVAL-TIMEOUT';
  return r.result && r.result.value;
};
let title = await evalT('document.title');
let html = await evalT(`document.getElementById('target').innerHTML`);
console.log('[STATE] title=' + title);
console.log('[STATE] innerHTML=' + html);

let shotSaved = false;
if (dialogs.length) {
  try {
    const shot = await b.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/drop_xss.png', Buffer.from(shot.data, 'base64'));
    shotSaved = true;
    console.log('[SHOT] saved drop_xss.png');
  } catch (e) { console.log('[SHOT] failed: ' + e.message); }
  await b.send('Page.handleJavaScriptDialog', { accept: true });
  await sleep(1000);
  title = await evalT('document.title');
  console.log('[STATE] titleAfterDismiss=' + title);
}
writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/readback.json', JSON.stringify({ title, html, dialogs: dialogs.map((d) => d.message), console: consoleEv, shotSaved }, null, 2));
console.log('READBACK-DONE');
process.exit(0);
