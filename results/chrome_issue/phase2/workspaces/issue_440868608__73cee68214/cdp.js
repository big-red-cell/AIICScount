// Minimal CDP client for Chrome reproduction (Node >= 22, global WebSocket).
const http = require('http');

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

async function getPageWs() {
  const list = await getJson('http://127.0.0.1:9222/json/list');
  // Prefer a page target that is not chrome://newtab if possible; else first page.
  const pages = list.filter((t) => t.type === 'page');
  const pick = pages.find((t) => !t.url.startsWith('chrome://newtab')) || pages[0];
  if (!pick) throw new Error('no page target');
  return pick.webSocketDebuggerUrl;
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.events = [];
  }
  open() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = () => resolve();
      this.ws.onerror = (e) => reject(new Error('ws error'));
      this.ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) reject(new Error(JSON.stringify(msg.error)));
          else resolve(msg.result);
        } else if (msg.method) {
          this.events.push(msg);
        }
      };
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  close() {
    try { this.ws.close(); } catch (e) {}
  }
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  const wsUrl = await getPageWs();
  const c = new CDP(wsUrl);
  await c.open();
  let out;
  switch (cmd) {
    case 'nav': {
      await c.send('Page.enable');
      const res = await c.send('Page.navigate', { url: args[0] });
      // wait for load event or small delay
      await new Promise((r) => setTimeout(r, 1500));
      out = res;
      break;
    }
    case 'eval': {
      const res = await c.send('Runtime.evaluate', {
        expression: args[0],
        returnByValue: true,
        awaitPromise: true,
      });
      if (res.exceptionDetails) {
        out = { exception: res.exceptionDetails.exception?.description || res.exceptionDetails.text };
      } else {
        out = res.result.value;
      }
      break;
    }
    case 'insert': {
      const res = await c.send('Input.insertText', { text: args[0] });
      out = res;
      break;
    }
    case 'key': {
      // args[0] = key name like 'Enter', 'Tab'
      const key = args[0];
      const map = {
        Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' },
        Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, text: '\t' },
        Escape: { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 },
      };
      const k = map[key] || { key, code: key, windowsVirtualKeyCode: key.charCodeAt(0) };
      await c.send('Input.dispatchKeyEvent', { type: 'keyDown', ...k });
      await c.send('Input.dispatchKeyEvent', { type: 'keyUp', ...k });
      out = 'sent ' + key;
      break;
    }
    case 'click': {
      const [x, y] = args.map(Number);
      await c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
      await c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
      out = `clicked ${x},${y}`;
      break;
    }
    case 'state': {
      const res = await c.send('Runtime.evaluate', {
        expression: 'JSON.stringify({url: location.href, title: document.title})',
        returnByValue: true,
      });
      out = JSON.parse(res.result.value);
      break;
    }
    default:
      out = { error: 'unknown cmd' };
  }
  console.log(JSON.stringify(out));
  c.close();
}

main().catch((e) => {
  console.error('ERR: ' + e.message);
  process.exit(1);
});
