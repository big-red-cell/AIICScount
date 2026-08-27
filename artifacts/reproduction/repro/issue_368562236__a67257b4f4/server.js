// Static file server serving the same dir on two ports (origin A: 8000, origin B: 8001)
const http = require('http');
const fs = require('fs');
const path = require('path');

const dir = process.argv[2] || __dirname;

function serve(port) {
  http.createServer((req, res) => {
    const urlPath = req.url.split('?')[0];
    const f = path.join(dir, urlPath === '/' ? 'index.html' : urlPath);
    fs.readFile(f, (e, d) => {
      if (e) { res.writeHead(404); res.end('not found: ' + urlPath); return; }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(d);
    });
  }).listen(port, '127.0.0.1', () => console.log('serving ' + dir + ' on 127.0.0.1:' + port));
}

serve(8000); // origin A (drag source)
serve(8001); // origin B (drop target)
console.log('ready');
