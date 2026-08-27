// Diagnose: dump source page DOM state
const CDP_PORT = 9222;
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const c = new CDP(ws);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString());
      if (msg.id && c.pending.has(msg.id)) {
        const { res, rej } = c.pending.get(msg.id);
        c.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      }
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true });
    return r;
  }
}
async function main() {
  const targets = await (await fetch('http://127.0.0.1:' + CDP_PORT + '/json/list')).json();
  for (const t of targets) {
    console.log('TARGET type=' + t.type + ' url=' + t.url + ' title=' + t.title);
  }
  for (const t of targets.filter(t => t.type === 'page')) {
    const c = await CDP.connect(t.webSocketDebuggerUrl);
    const r = await c.evaluate('document.documentElement.outerHTML');
    console.log('=== DOM for ' + t.url + ' ===');
    console.log(r.result && r.result.value ? r.result.value : JSON.stringify(r));
    c.ws.close();
  }
}
main().catch(e => { console.error('ERR ' + e.message); process.exit(1); });
