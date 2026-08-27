import { writeFileSync } from 'fs';
import { get as httpGet } from 'http';
const getJSON = (url) => new Promise((res, rej) => {
  httpGet(url, (r) => { let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d))); }).on('error', rej);
});
const list = await getJSON('http://127.0.0.1:9222/json/list');
const tab = list.find(t => t.type === 'page');
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Page.navigate', { url: 'chrome://download-internals/' });
await new Promise(r => setTimeout(r, 4000));
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:\\Codes\\agents\\aiic_three_stage_pipeline\\artifacts\\reproduction\\repro\\issue_385263984__060d45f1a9\\download_internals_after.png', Buffer.from(shot.data, 'base64'));
console.log('screenshot saved, bytes:', Buffer.from(shot.data, 'base64').length);
process.exit(0);
