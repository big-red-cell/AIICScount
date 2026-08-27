// CDP driver: reproduces cross-origin drag & drop of text/html into a contenteditable
// element. Source page (dragme.html @127.0.0.1:8000) sets text/html payload in a real
// trusted dragstart. The drop is dispatched into dropme.html @127.0.0.1:8001.
// Evidence readback: Input.dragIntercepted data, Page.javascriptDialogOpening, DOM innerHTML.

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
      } else if (msg.method) {
        c.events.push(msg);
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
  waitEvent(method, timeoutMs = 15000) {
    return new Promise((res, rej) => {
      const t0 = Date.now();
      const tick = () => {
        const i = this.events.findIndex(e => e.method === method);
        if (i >= 0) return res(this.events.splice(i, 1)[0]);
        if (Date.now() - t0 > timeoutMs) return rej(new Error('timeout waiting for ' + method));
        setTimeout(tick, 50);
      };
      tick();
    });
  }
  async evaluate(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch (e) {} }
}

async function getTargets() {
  const res = await fetch('http://127.0.0.1:' + CDP_PORT + '/json/list');
  return res.json();
}

function center(rect) {
  return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
}

async function main() {
  // wait for both pages
  let targets;
  for (let i = 0; i < 30; i++) {
    targets = await getTargets();
    if (targets.some(t => t.url === SOURCE_URL) && targets.some(t => t.url === TARGET_URL)) break;
    await new Promise(r => setTimeout(r, 500));
  }
  const srcT = targets.find(t => t.url === SOURCE_URL);
  const dstT = targets.find(t => t.url === TARGET_URL);
  if (!srcT || !dstT) throw new Error('pages not found: ' + JSON.stringify(targets.map(t => t.url)));

  const src = await CDP.connect(srcT.webSocketDebuggerUrl);
  const dst = await CDP.connect(dstT.webSocketDebuggerUrl);

  await src.send('Page.enable');
  await src.send('Runtime.enable');
  await dst.send('Page.enable');
  await dst.send('Runtime.enable');

  console.log('VERIFY target_url=' + (await dst.evaluate('location.href')));
  console.log('VERIFY source_url=' + (await src.evaluate('location.href')));
  console.log('VERIFY target_origin=' + (await dst.evaluate('location.origin')));
  console.log('VERIFY source_origin=' + (await src.evaluate('location.origin')));

  // Intercept the real drag started in the source page so we can capture the
  // DataTransfer items the source origin actually set.
  await src.send('Input.setInterceptDrags', { enabled: true });

  const srcRect = await src.evaluate(`(() => { const r = document.getElementById('draggable').getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()`);
  const dstRect = await dst.evaluate(`(() => { const r = document.getElementById('dropzone').getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()`);
  const srcC = center(srcRect);
  const dstC = center(dstRect);
  console.log('INFO src_center=' + JSON.stringify(srcC) + ' dst_center=' + JSON.stringify(dstC));

  // Perform the physical drag on the source page: press, move (drag starts), release.
  await src.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: srcC.x, y: srcC.y, button: 'left', buttons: 1, clickCount: 1 });
  await src.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: srcC.x + 12, y: srcC.y + 12, button: 'left', buttons: 1 });
  const intercepted = await src.waitEvent('Input.dragIntercepted', 10000);
  const dragData = intercepted.params.data;
  console.log('VERIFY dragIntercepted_items=' + JSON.stringify(dragData.items));
  const htmlItem = (dragData.items || []).find(i => i.mimeType === 'text/html');
  if (!htmlItem) throw new Error('no text/html item in intercepted drag data');
  console.log('VERIFY drag_html_payload=' + JSON.stringify(htmlItem.data));
  await src.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: srcC.x + 12, y: srcC.y + 12, button: 'left', buttons: 0, clickCount: 1 });

  // Drop into the target contenteditable (origin B).
  const ops = 1; // copy
  await dst.send('Input.dispatchDragEvent', { type: 'dragEnter', x: dstC.x, y: dstC.y, data: dragData });
  await dst.send('Input.dispatchDragEvent', { type: 'dragOver', x: dstC.x, y: dstC.y, data: dragData, dragOperationsMask: ops });
  await dst.send('Input.dispatchDragEvent', { type: 'drop', x: dstC.x, y: dstC.y, data: dragData, dragOperationsMask: ops });
  console.log('INFO drop_dispatched_at=' + JSON.stringify(dstC));

  // Readback 1: did a JS dialog (alert) open in the drop page?
  let dialogMsg = null;
  try {
    const ev = await dst.waitEvent('Page.javascriptDialogOpening', 8000);
    dialogMsg = ev.params.message;
    console.log('VERIFY javascriptDialogOpening_message=' + JSON.stringify(dialogMsg));
    await dst.send('Page.handleJavaScriptDialog', { accept: true });
  } catch (e) {
    console.log('NO_DIALOG ' + e.message);
  }

  // Readback 2: DOM state of the contenteditable after the drop.
  const innerHTML = await dst.evaluate(`document.getElementById('dropzone').innerHTML`);
  console.log('VERIFY dropzone_innerHTML=' + JSON.stringify(innerHTML));

  src.close(); dst.close();
  process.exit(dialogMsg ? 0 : 2);
}

main().catch(e => { console.error('DRIVER_ERROR ' + e.stack); process.exit(1); });
