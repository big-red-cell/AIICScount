// Minimal static file server for the repro web dir
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const root = process.argv[2];
const port = Number(process.argv[3] || 8765);
const types = { '.html': 'text/html', '.png': 'image/png', '.gif': 'image/gif', '.svg': 'image/svg+xml', '.js': 'text/javascript', '.css': 'text/css' };

http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/lure.html';
  const fp = path.join(root, p);
  fs.readFile(fp, (err, data) => {
    if (err) { res.writeHead(404); res.end('nf'); return; }
    res.writeHead(200, { 'Content-Type': types[path.extname(fp)] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(port, '127.0.0.1', () => console.log('SERVER_READY ' + port));
