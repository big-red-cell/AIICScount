// Minimal CDP helper using Node's built-in fetch + WebSocket.
// usage:
//   node cdp.js new <url>          -> creates tab, prints target JSON (id + webSocketDebuggerUrl)
//   node cdp.js list               -> list targets
//   node cdp.js eval <ws> <expr>   -> Runtime.evaluate with returnByValue + awaitPromise
//   node cdp.js nav <ws> <url>     -> navigate current tab
//   node cdp.js close <id>         -> close tab
const base = 'http://127.0.0.1:9222';
const [,, cmd, a, b] = process.argv;

function evalOn(wsUrl, expression) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => {
      ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression, returnByValue: true, awaitPromise: true } }));
    };
    ws.onmessage = e => {
      const m = JSON.parse(e.data);
      if (m.id === 1) { ws.close(); resolve(m); }
    };
    ws.onerror = reject;
  });
}

async function main() {
  if (cmd === 'new') {
    const res = await fetch(`${base}/json/new?${encodeURIComponent(a)}`, { method: 'PUT' });
    console.log(JSON.stringify(await res.json()));
  } else if (cmd === 'list') {
    const res = await fetch(`${base}/json/list`);
    console.log(JSON.stringify(await res.json(), null, 2));
  } else if (cmd === 'eval') {
    console.log(JSON.stringify(await evalOn(a, b), null, 2));
  } else if (cmd === 'nav') {
    const ws = new WebSocket(a);
    await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
    ws.send(JSON.stringify({ id: 1, method: 'Page.navigate', params: { url: b } }));
    const res = await new Promise((resolve, reject) => {
      ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id === 1) resolve(m); };
      ws.onerror = reject;
    });
    console.log(JSON.stringify(res));
    ws.close();
  } else if (cmd === 'close') {
    const res = await fetch(`${base}/json/close/${a}`);
    console.log(res.status);
  }
}
main().catch(e => { console.error('ERR', e.message); process.exit(1); });
