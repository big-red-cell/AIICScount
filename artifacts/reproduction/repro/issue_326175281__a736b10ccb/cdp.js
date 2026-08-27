// CDP helper for Chrome reproduction. Modes:
//   nav <url>                 navigate active page tab, print URL + title
//   eval <expr>               Runtime.evaluate, print value
//   keys <spec>               key sequence: ctrl+l | ctrl+shift+b | type:<text> | enter (semicolon separated)
//   wait-dialog <seconds>     enable Page, wait for javascriptDialogOpening, print message, accept
'use strict';
const http = require('http');

const WS_URL = 'http://127.0.0.1:9222';

function httpGet(url) {
  return new Promise((res, rej) => {
    http.get(url, r => {
      let d = '';
      r.on('data', c => (d += c));
      r.on('end', () => res(d));
    }).on('error', rej);
  });
}

async function getPageWs() {
  const list = JSON.parse(await httpGet(WS_URL + '/json/list'));
  const page = list.find(t => t.type === 'page');
  if (!page) throw new Error('no page target found: ' + JSON.stringify(list.map(t => t.type)));
  return page.webSocketDebuggerUrl;
}

async function connect() {
  const ws = new WebSocket(await getPageWs());
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id) {
      const p = pending.get(m.id);
      if (p) { pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); }
    } else {
      listeners.forEach(l => l(m));
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = ++id;
    pending.set(i, { res, rej });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  return { ws, send, onEvent: fn => listeners.push(fn) };
}

async function main() {
  const mode = process.argv[2];
  const arg = process.argv[3];
  if (mode === 'nav') {
    const c = await connect();
    await c.send('Page.enable');
    await c.send('Page.navigate', { url: arg });
    await new Promise(r => setTimeout(r, 2500));
    const { result } = await c.send('Runtime.evaluate', { expression: 'location.href + " ||| " + document.title', returnByValue: true });
    console.log('NAV_RESULT: ' + result.value);
    c.ws.close();
  } else if (mode === 'eval') {
    const c = await connect();
    const { result } = await c.send('Runtime.evaluate', { expression: arg, returnByValue: true });
    console.log('EVAL_RESULT: ' + JSON.stringify(result.value));
    c.ws.close();
  } else if (mode === 'keys') {
    const c = await connect();
    const steps = arg.split(';');
    for (const s of steps) {
      if (s === 'ctrl+l') {
        await c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', modifiers: 2, key: 'l', code: 'KeyL', windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });
        await c.send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 2, key: 'l', code: 'KeyL', windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });
      } else if (s === 'ctrl+shift+b') {
        await c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', modifiers: 10, key: 'b', code: 'KeyB', windowsVirtualKeyCode: 66, nativeVirtualKeyCode: 66 });
        await c.send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 10, key: 'b', code: 'KeyB', windowsVirtualKeyCode: 66, nativeVirtualKeyCode: 66 });
      } else if (s.startsWith('type:')) {
        await c.send('Input.insertText', { text: s.slice(5) });
      } else if (s === 'enter') {
        await c.send('Input.dispatchKeyEvent', { type: 'keyDown', modifiers: 0, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: '\r', unmodifiedText: '\r' });
        await c.send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 0, key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
      } else if (s === 'tab') {
        await c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', modifiers: 0, key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
        await c.send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 0, key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 });
      }
      await new Promise(r => setTimeout(r, 300));
    }
    console.log('KEYS_SENT: ' + arg);
    c.ws.close();
  } else if (mode === 'wait-dialog') {
    const secs = parseInt(arg || '20', 10);
    const c = await connect();
    await c.send('Page.enable');
    let dialog = null;
    c.onEvent(m => {
      if (m.method === 'Page.javascriptDialogOpening') {
        dialog = m.params;
        console.log('DIALOG_OPEN: message=' + JSON.stringify(m.params.message) + ' type=' + m.params.type + ' url=' + m.params.url);
      }
    });
    const start = Date.now();
    while (!dialog && Date.now() - start < secs * 1000) {
      await new Promise(r => setTimeout(r, 200));
    }
    if (dialog) {
      await c.send('Page.handleJavaScriptDialog', { accept: true });
      console.log('DIALOG_ACCEPTED');
    } else {
      console.log('DIALOG_TIMEOUT');
    }
    c.ws.close();
  } else {
    console.log('unknown mode');
    process.exit(2);
  }
}

main().catch(e => { console.error('ERR: ' + e.message); process.exit(1); });
