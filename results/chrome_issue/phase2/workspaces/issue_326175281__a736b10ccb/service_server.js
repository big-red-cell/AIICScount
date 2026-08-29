// Local "logged-in service" for repro: sets a session cookie and serves a page.
'use strict';
const http = require('http');
http.createServer((req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Set-Cookie': 'session=SECRET12345; Path=/'
  });
  res.end('<!DOCTYPE html><html><head><title>Logged-in Service</title></head><body><h1>You are logged in</h1><p>cookie header: ' + (req.headers.cookie || '(none)') + '</p></body></html>');
}).listen(8899, '127.0.0.1', () => console.log('service listening on 127.0.0.1:8899'));
