// CDP: navigate fresh tab to the issue URL and read back state.
const http = require('http');
function getJSON(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => { let d=''; res.on('data',c=>d+=c); res.on('end',()=>{try{resolve(JSON.parse(d))}catch(e){reject(e)}}); }).on('error', reject);
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function main() {
  const targets = await getJSON('http://127.0.0.1:9222/json/list');
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let msgId = 0; const pending = new Map();
  ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const send = (method, params = {}) => new Promise((resolve) => { const mid = ++msgId; pending.set(mid, resolve); ws.send(JSON.stringify({ id: mid, method, params })); });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: 'https://1:1@httpbin.org/basic-auth/1/1' });
  await sleep(6000);
  const loc = await send('Runtime.evaluate', { expression: 'location.href', returnByValue: true });
  const body = await send('Runtime.evaluate', { expression: 'document.body ? document.body.innerText.slice(0,200) : "(no body)"', returnByValue: true });
  console.log('LOCATION_HREF:', JSON.stringify(loc.result.result.value));
  console.log('BODY:', JSON.stringify(body.result.result.value));
  ws.close(); process.exit(0);
}
main().catch((e) => { console.error('ERR', e); process.exit(1); });
