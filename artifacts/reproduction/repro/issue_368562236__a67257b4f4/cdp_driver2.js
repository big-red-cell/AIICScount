// CDP driver v2: cross-origin drag & drop of text/html into contenteditable.
// Attempt A: real intercepted drag from source page (Input.setInterceptDrags).
// Attempt B (fallback): build dragData by invoking the source page's own dragstart
// listener with a real DataTransfer, then dispatch dragEnter/dragOver/drop on target.

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
    if (r.exceptionDetails) throw new Error('eval exception: ' + JSON.stringify(r.exceptionDetails.exception.description || r.exceptionDetails));
    return r.result.value;
  }
  close() { try { this.ws.close(); } catch (e) {} }
}

async function getTargets() {
  return (await fetch('http://127.0.0.1:' + CDP_PORT + '/json/list')).json();
}
function center(rect) {
  return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  let targets;
  for (let i = 0; i < 30; i++) {
    targets = await getTargets();
    if (targets.some(t => t.url === SOURCE_URL) && targets.some(t => t.url === TARGET_URL)) break;
    await sleep(500);
  }
  const srcT = targets.find(t => t.url === SOURCE_URL);
  const dstT = targets.find(t => t.url === TARGET_URL);
  if (!srcT || !dstT) throw new Error('pages not found');

  const src = await CDP.connect(srcT.webSocketDebuggerUrl);
  const dst = await CDP.connect(dstT.webSocketDebuggerUrl);
  await src.send('Page.enable'); await src.send('Runtime.enable');
  await dst.send('Page.enable'); await dst.send('Runtime.enable');

  console.log('VERIFY target_url=' + (await dst.evaluate('location.href')));
  console.log('VERIFY source_url=' + (await src.evaluate('location.href')));
  console.log('VERIFY target_origin=' + (await dst.evaluate('location.origin')));
  console.log('VERIFY source_origin=' + (await src.evaluate('location.origin')));

  const srcRect = await src.evaluate(`(() => { const r = document.getElementById('draggable').getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()`);
  const dstRect = await dst.evaluate(`(() => { const r = document.getElementById('dropzone').getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; })()`);
  const srcC = center(srcRect);
  const dstC = center(dstRect);
  console.log('INFO src_center=' + JSON.stringify(srcC) + ' dst_center=' + JSON.stringify(dstC));

  let dragData = null;

  // ---- Attempt A: real intercepted drag ----
  await src.send('Page.bringToFront');
  await src.send('Input.setInterceptDrags', { enabled: true });
  await src.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: srcC.x, y: srcC.y, button: 'left', buttons: 1, clickCount: 1 });
  for (const dx of [4, 8, 16, 24]) {
    await src.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: srcC.x + dx, y: srcC.y + 6, button: 'left', buttons: 1 });
    await sleep(80);
  }
  try {
    const intercepted = await src.waitEvent('Input.dragIntercepted', 8000);
    dragData = intercepted.params.data;
    console.log('VERIFY dragIntercepted_items=' + JSON.stringify(dragData.items));
  } catch (e) {
    console.log('ATTEMPT_A_FAILED ' + e.message);
  }
  await src.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: srcC.x + 24, y: srcC.y + 6, button: 'left', buttons: 0, clickCount: 1 });

  // ---- Attempt B: build dragData from the source page's own dragstart handler ----
  if (!dragData) {
    console.log('INFO using attempt B (synthetic dragstart in source origin)');
    const items = await src.evaluate(`new Promise((resolve) => {
      const el = document.getElementById('draggable');
      const dt = new DataTransfer();
      const ev = new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt });
      el.dispatchEvent(ev);
      const out = [];
      for (const t of dt.types) out.push({ mimeType: t, data: dt.getData(t) });
      resolve(out);
    })`);
    console.log('VERIFY source_dragstart_items=' + JSON.stringify(items));
    dragData = { items, files: [], dragOperationsMask: 1 };
  }

  const htmlItem = (dragData.items || []).find(i => i.mimeType === 'text/html');
  if (!htmlItem) throw new Error('no text/html item');
  console.log('VERIFY drag_html_payload=' + JSON.stringify(htmlItem.data));

  // ---- Drop into target contenteditable (origin B) ----
  await dst.send('Page.bringToFront');
  await dst.send('Input.dispatchDragEvent', { type: 'dragEnter', x: dstC.x, y: dstC.y, data: dragData });
  await dst.send('Input.dispatchDragEvent', { type: 'dragOver', x: dstC.x, y: dstC.y, data: dragData, dragOperationsMask: 1 });
  await dst.send('Input.dispatchDragEvent', { type: 'drop', x: dstC.x, y: dstC.y, data: dragData, dragOperationsMask: 1 });
  console.log('INFO drop_dispatched_at=' + JSON.stringify(dstC));

  let dialogMsg = null;
  try {
    const ev = await dst.waitEvent('Page.javascriptDialogOpening', 8000);
    dialogMsg = ev.params.message;
    console.log('VERIFY javascriptDialogOpening_message=' + JSON.stringify(dialogMsg));
    await dst.send('Page.handleJavaScriptDialog', { accept: true });
  } catch (e) {
    console.log('NO_DIALOG ' + e.message);
  }

  const innerHTML = await dst.evaluate(`document.getElementById('dropzone').innerHTML`);
  console.log('VERIFY dropzone_innerHTML=' + JSON.stringify(innerHTML));

  src.close(); dst.close();
  process.exit(dialogMsg ? 0 : 2);
}

main().catch(e => { console.error('DRIVER_ERROR ' + e.stack); process.exit(1); });
