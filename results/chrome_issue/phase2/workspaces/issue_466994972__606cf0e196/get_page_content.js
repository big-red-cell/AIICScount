const WebSocket = require('ws');

const wsUrl = 'ws://127.0.0.1:9222/devtools/page/F9759576C2CF36B661CFBC322ABD4A07';
const ws = new WebSocket(wsUrl);

ws.on('open', () => {
  console.log('Connected to Chrome DevTools');
  
  // Enable DOM domain
  ws.send(JSON.stringify({
    id: 1,
    method: 'DOM.enable'
  }));
  
  // Get document
  ws.send(JSON.stringify({
    id: 2,
    method: 'DOM.getDocument'
  }));
});

ws.on('message', (data) => {
  const response = JSON.parse(data);
  
  if (response.id === 2) {
    // Get the root node ID
    const nodeId = response.result.root.nodeId;
    
    // Query for anchor tags
    ws.send(JSON.stringify({
      id: 3,
      method: 'DOM.querySelectorAll',
      params: {
        nodeId: nodeId,
        selector: 'a[href*="dist.torproject.org"]'
      }
    }));
  }
  
  if (response.id === 3) {
    if (response.result && response.result.nodeIds && response.result.nodeIds.length > 0) {
      const linkNodeId = response.result.nodeIds[0];
      
      // Get the href attribute of the link
      ws.send(JSON.stringify({
        id: 4,
        method: 'DOM.getAttributes',
        params: {
          nodeId: linkNodeId
        }
      }));
    } else {
      console.log('No matching links found');
      process.exit(1);
    }
  }
  
  if (response.id === 4) {
    const attributes = response.result.attributes;
    // Find the href attribute
    for (let i = 0; i < attributes.length; i += 2) {
      if (attributes[i] === 'href') {
        console.log('Found download link:', attributes[i + 1]);
        // Click the link
        ws.send(JSON.stringify({
          id: 5,
          method: 'DOM.dispatchEvent',
          params: {
            nodeId: response.result.nodeId,
            eventName: 'click'
          }
        }));
        break;
      }
    }
  }
});

ws.on('error', (error) => {
  console.error('WebSocket error:', error);
  process.exit(1);
});

ws.on('close', () => {
  console.log('WebSocket closed');
});