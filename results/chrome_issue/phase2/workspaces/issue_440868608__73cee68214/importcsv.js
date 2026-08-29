// Click the "选择文件" button with file chooser interception, then handle chooser.
const http = require('http');
const path = require('path');
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
  const events = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
    else if (m.method) events.push(m.method + (m.params.backendNodeId ? ' backend=' + m.params.backendNodeId : '') + (m.params.mode ? ' mode=' + m.params.mode : ''));
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const i = ++id; pending.set(i, (r) => (r.error ? rej(new Error(JSON.stringify(r.error))) : res(r.result))); ws.send(JSON.stringify({ id: i, method, params }));
  });
  await new Promise((res) => (ws.onopen = res));
  await send('Page.enable');
  await send('Page.setInterceptFileChooserDialog', { enabled: true });
  const clickRes = await send('Runtime.evaluate', {
    expression: `(()=>{function find(root,out){if(!root)return;for(const el of root.querySelectorAll('*')){const t=(el.textContent||'').trim();if(t.includes('选择文件')&&el.tagName==='CR-BUTTON'){out.push(el);}if(el.shadowRoot)find(el.shadowRoot,out);}}const out=[];find(document,out);if(!out.length)return 'no choose-file button';out[0].click();return 'clicked choose-file';})()`,
    returnByValue: true,
  });
  console.log('click:', clickRes.value);
  await new Promise((r) => setTimeout(r, 1500));
  console.log('events:', events.join(' | ') || '(none)');
  if (events.some((e) => e.startsWith('Page.fileChooserOpened'))) {
    const csvPath = path.resolve(__dirname, 'passwords_import.csv');
    const hf = await send('Page.handleFileChooser', { files: [csvPath] }).catch((e) => ({ err: e.message }));
    console.log('handleFileChooser:', JSON.stringify(hf));
  } else {
    console.log('no chooser event');
  }
  await new Promise((r) => setTimeout(r, 3000));
  const st = await send('Runtime.evaluate', {
    expression: `(()=>{function texts(root,out){if(!root)return;for(const el of root.querySelectorAll('*')){if(el.children.length===0){const t=(el.textContent||'').trim();if(t&&t.length<150)out.push(el.tagName+': '+t);}if(el.shadowRoot)texts(el.shadowRoot,out);}}const out=[];texts(document,out);return out.slice(0,60).join(' | ');})()`,
    returnByValue: true,
  });
  console.log('page:', (st.value || '').slice(0, 1400));
  ws.close();
})();
