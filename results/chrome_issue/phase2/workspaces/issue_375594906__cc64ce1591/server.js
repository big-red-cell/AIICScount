// Minimal static file server for the repro site (port 8123).
const http = require('http');
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, 'site');
const port = 8123;
http.createServer((req, res) => {
  const p = path.join(dir, req.url === '/' ? 'os.html' : req.url.replace(/^\//, ''));
  fs.readFile(p, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(data);
  });
}).listen(port, () => console.log('serving on http://127.0.0.1:' + port));
