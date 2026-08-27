// Attach, enable console/log, click addButton, dump any console errors.
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
  const logs = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
    else if (m.method === 'Runtime.consoleAPICalled' || m.method === 'Runtime.exceptionThrown' || m.method === 'Log.entryAdded') {
      logs.push(JSON.stringify(m).slice(0, 500));
    }
  };
  const send = (method, params = {}) => new Promise((res) => {
    const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params }));
  });
  await new Promise((res) => (ws.onopen = res));
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Runtime.evaluate', { expression: `(()=>{function find(root,out){if(!root)return;for(const el of root.querySelectorAll('*')){if(el.tagName==='CR-DIALOG'&&el.id==='dialog'){out.push(el);}if(el.shadowRoot)find(el.shadowRoot,out);}}const out=[];find(document,out);const dlg=out[0];dlg.querySelector('#addButton').click();return 'clicked';})()`, returnByValue: true });
  await new Promise((r) => setTimeout(r, 2500));
  const state = await send('Runtime.evaluate', { expression: `(()=>{function find(root,out){if(!root)return;for(const el of root.querySelectorAll('*')){if(el.tagName==='CR-DIALOG'&&el.id==='dialog'){out.push(el);}if(el.shadowRoot)find(el.shadowRoot,out);}}const out=[];find(document,out);return JSON.stringify({dialogOpen: out.length?out[0].open:false});})()`, returnByValue: true });
  console.log('state:', state.result.value);
  console.log('logs:', logs.length ? logs.join('\n---\n') : '(none)');
  ws.close();
})();
