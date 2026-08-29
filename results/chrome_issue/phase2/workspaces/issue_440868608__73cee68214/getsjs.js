// Fetch password_manager.js source via Network domain.
const http = require('http');
function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => res(JSON.parse(d))); }).on('error', rej);
  });
}
(async () => {
  console.log('step1: get targets');
  const list = await getJson('http://127.0.0.1:9222/json/list');
  const page = list.find((t) => t.type === 'page');
  console.log('target:', page.url);
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
  console.log('step2: enable + reload');
  await send('Network.enable');
  await send('Page.enable');
  await send('Page.reload', { ignoreCache: true });
  await new Promise((r) => setTimeout(r, 3500));
  console.log('step3: reqs captured:', reqs.length);
  if (reqs.length) {
    const body = await send('Network.getResponseBody', { requestId: reqs[0] });
    const t = body.body;
    const i = t.indexOf('onAddClick_');
    console.log('step4: source length', t.length, 'idx', i);
    if (i >= 0) {
      const start = Math.max(0, i - 400);
      console.log(t.slice(start, i + 800));
    } else {
      // search for assert lines near "AddPasswordDialog"
      const j = t.indexOf('AddPasswordDialog');
      console.log(t.slice(j, j + 2000));
    }
  } else {
    console.log('step3b: no request captured; list all requests seen? none');
  }
  ws.close();
  process.exit(0);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
