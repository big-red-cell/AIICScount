// Navigate the first about:blank page tab to a credentialed URL and report frame URL.
async function main() {
  const res = await fetch('http://127.0.0.1:9222/json/list');
  const list = await res.json();
  const page = list.find(t => t.type === 'page' && t.url === 'about:blank');
  if (!page) throw new Error('no about:blank page target');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const frames = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else if (msg.method === 'Page.frameNavigated') {
      frames.push(msg.params.frame.url);
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
  await send('Page.navigate', { url: 'https://2:2@httpbin.org/basic-auth/2/2' });
  let state = '';
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 500));
    try { state = (await send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true })).result.value; } catch (e) {}
    if (state === 'complete') break;
  }
  console.log('READYSTATE: ' + state);
  const body = (await send('Runtime.evaluate', { expression: 'document.body ? document.body.innerText : ""', returnByValue: true })).result.value;
  console.log('BODY: ' + body.replace(/\s+/g, ' ').trim().slice(0, 200));
  console.log('FRAME_URLS: ' + JSON.stringify(frames));
  ws.close();
}
main().catch(e => { console.error('ERROR: ' + e.message); process.exit(1); });
