// Create two separate Chrome windows (dragme at :8000, dropme at :8001), position them side by side.
import { writeFileSync } from 'node:fs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class CDP {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.id = 0; this.pending = new Map(); }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = (e) => { console.error('WS ERROR', e.message || e); rej(e); }; });
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { res, rej } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      } else {
        console.log('[EVENT]', JSON.stringify(msg).slice(0, 300));
      }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      const to = setTimeout(() => rej(new Error('timeout waiting ' + method)), 15000);
      this.pending.set(id, { res: (v) => { clearTimeout(to); res(v); }, rej: (e) => { clearTimeout(to); rej(e); } });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

const base = 'http://127.0.0.1:9222';
const ver = await (await fetch(base + '/json/version')).json();
const b = new CDP(ver.webSocketDebuggerUrl);
await b.open();

// close existing extra tabs to keep things clean (keep first two: dragme/dropme)
let list = await (await fetch(base + '/json/list')).json();
for (const t of list.filter((t) => t.type === 'page')) {
  await fetch(base + '/json/close/' + t.id);
  await sleep(150);
}
await sleep(500);

const tA = await b.send('Target.createTarget', { url: 'http://127.0.0.1:8000/dragme.html', newWindow: true });
const tB = await b.send('Target.createTarget', { url: 'http://127.0.0.1:8001/dropme.html', newWindow: true });
await sleep(2000);

const wA = await b.send('Browser.getWindowForTarget', { targetId: tA.targetId });
const wB = await b.send('Browser.getWindowForTarget', { targetId: tB.targetId });
await b.send('Browser.setWindowBounds', { windowId: wA.windowId, bounds: { left: 0, top: 0, width: 520, height: 620, windowState: 'normal' } });
await b.send('Browser.setWindowBounds', { windowId: wB.windowId, bounds: { left: 700, top: 0, width: 520, height: 620, windowState: 'normal' } });
await sleep(1500);

const info = { targetA: tA.targetId, targetB: tB.targetId, windowA: wA.windowId, windowB: wB.windowId };
writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/windows.json', JSON.stringify(info, null, 2));
console.log(JSON.stringify(info));
process.exit(0);
