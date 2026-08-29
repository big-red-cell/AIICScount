// Send N Enter keyDown events (held key) to a tab via CDP.
// usage: node keyenter.js <wsUrl> <count>
const wsUrl = process.argv[2];
const count = parseInt(process.argv[3] || '6', 10);
const ws = new WebSocket(wsUrl);
let sent = 0;
ws.onopen = () => {
  const send = () => {
    if (sent >= count) { setTimeout(() => { ws.close(); }, 300); return; }
    sent++;
    ws.send(JSON.stringify({
      id: sent,
      method: 'Input.dispatchKeyEvent',
      params: {
        type: 'keyDown',
        key: 'Enter',
        code: 'Enter',
        windowsVirtualKeyCode: 13,
        nativeVirtualKeyCode: 13,
        text: '\r',
        unmodifiedText: '\r'
      }
    }));
    setTimeout(send, 60);
  };
  send();
};
ws.onerror = e => { console.error('ws error', e.message || ''); process.exit(1); };
ws.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.id === sent) console.log('sent keyDown #' + sent);
};
