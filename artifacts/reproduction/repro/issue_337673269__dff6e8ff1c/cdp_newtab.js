// Create a new tab, navigate to the credentialed URL, verify committed frame URL.
async function main() {
  const res = await fetch('http://127.0.0.1:9222/json/new?' + encodeURIComponent('https://1:1@httpbin.org/basic-auth/1/1'), { method: 'PUT' });
  const target = await res.json();
  console.log('NEW_TAB: ' + target.id + ' url=' + target.url);

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    }
  };
  await new Promise((res2, rej) => { ws.onopen = res2; ws.onerror = rej; });
  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const mid = ++id;
      pending.set(mid, { resolve, reject });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  }
  await send('Page.enable');
  await send('Runtime.enable');
  // wait for load
  let state = '';
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 500));
    try { state = (await send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true })).result.value; } catch (e) {}
    if (state === 'complete') break;
  }
  console.log('READYSTATE: ' + state);
  const href = (await send('Runtime.evaluate', { expression: 'location.href', returnByValue: true })).result.value;
  console.log('JS_HREF: ' + href);
  const body = (await send('Runtime.evaluate', { expression: 'document.body ? document.body.innerText : ""', returnByValue: true })).result.value;
  console.log('BODY: ' + body.replace(/\s+/g, ' ').trim().slice(0, 200));
  ws.close();
}
main().catch(e => { console.error('ERROR: ' + e.message); process.exit(1); });
