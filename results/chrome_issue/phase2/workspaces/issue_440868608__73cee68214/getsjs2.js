// Print onAddClick_ implementation + canAddPassword_ from password_manager.js
const http = require('http');
function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => res(JSON.parse(d))); }).on('error', rej);
  });
}
(async () => {
  const list = await getJson('http://127.0.0.1:9222/json/list');
  const page = list.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const reqs = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
    else if (m.method === 'Network.requestWillBeSent' && m.params.request.url.includes('password_manager.js')) {
      reqs.push(m.params.requestId);
    }
  };
  const send = (method, params = {}) => new Promise((res) => {
    const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params }));
  });
  await new Promise((res) => (ws.onopen = res));
  await send('Network.enable');
  await send('Page.enable');
  await send('Page.reload', { ignoreCache: true });
  await new Promise((r) => setTimeout(r, 3500));
  const body = await send('Network.getResponseBody', { requestId: reqs[0] });
  const t = body.body;
  const grab = (name, len) => {
    const i = t.indexOf(name);
    if (i < 0) return name + ': NOT FOUND';
    return t.slice(i, i + len);
  };
  console.log('=== onAddClick_ ===');
  console.log(grab('onAddClick_()', 600));
  console.log('=== canAddPassword_ ===');
  console.log(grab('canAddPassword_', 400));
  console.log('=== save-password dispatch ===');
  console.log(grab("'save-password'", 600));
  ws.close();
  process.exit(0);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
