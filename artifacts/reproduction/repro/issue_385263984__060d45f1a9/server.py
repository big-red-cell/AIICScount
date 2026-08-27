import http.server, socketserver, sys, json, time, os

LOG = r"D:\Codes\agents\aiic_three_stage_pipeline\artifacts\reproduction\repro\issue_385263984__060d45f1a9\requests.log"
HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 18080

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args):
        pass
    def _log(self):
        entry = {
            "time": round(time.time(), 3),
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers),
        }
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        self._log()
        p = self.path.split("?")[0]
        if p == "/set":
            body = b"<html><body><h1>cookie set page</h1></body></html>"
            self._send(200, "text/html", body, {"Set-Cookie": "test=test; SameSite=Strict; Path=/"})
        elif p == "/cookies":
            body = b"cookie-probe-body"
            self._send(200, "text/plain", body, {"Content-Disposition": 'attachment; filename="probe.txt"'})
        elif p == "/xsite":
            body = b'<html><body><img src="http://127.0.0.1:18080/cookies" id="probeimg"></body></html>'
            self._send(200, "text/html", body)
        elif p == "/marker":
            self._send(200, "text/plain", b"marker-ok")
        else:
            self._send(200, "text/plain", b"ok")

with socketserver.ThreadingTCPServer((HOST, PORT), H) as httpd:
    print("listening on %s:%d" % (HOST, PORT), flush=True)
    httpd.serve_forever()
