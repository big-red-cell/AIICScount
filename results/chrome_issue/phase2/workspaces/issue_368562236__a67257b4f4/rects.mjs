// Read CSS rects of #drag (window A, :8000) and #target (window B, :8001) via page CDP.
import { writeFileSync } from 'node:fs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
class CDP {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.id = 0; this.pending = new Map(); }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = rej; });
    this.ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { res, rej } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => { this.pending.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
}
const evalIn = async (c, expr) => {
  const r = await c.send('Runtime.evaluate', { expression: expr, returnByValue: true });
  return r.result && r.result.value;
};

const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const tabA = list.find((t) => t.type === 'page' && t.url.includes('dragme'));
const tabB = list.find((t) => t.type === 'page' && t.url.includes('dropme'));
const a = new CDP(tabA.webSocketDebuggerUrl); await a.open(); await a.send('Runtime.enable');
const b = new CDP(tabB.webSocketDebuggerUrl); await b.open(); await b.send('Runtime.enable');
await sleep(800);
const rectA = JSON.parse(await evalIn(a, `JSON.stringify(document.getElementById('drag').getBoundingClientRect())`));
const rectB = JSON.parse(await evalIn(b, `JSON.stringify(document.getElementById('target').getBoundingClientRect())`));
const titleA = await evalIn(a, 'document.title');
const titleB = await evalIn(b, 'document.title');
const out = { rectA, rectB, titleA, titleB };
writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/rects.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify(out));
process.exit(0);
