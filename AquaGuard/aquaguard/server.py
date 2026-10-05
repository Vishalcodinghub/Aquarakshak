"""Tiny HTTP server: serves the dashboard (static/) and the JSON mock-IoT API (/api/*)."""
import json
import os
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .engine import Engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
STORE = os.path.join(ROOT, "data", "store.json")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=STATIC, **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, TimeoutError):
            pass

    def guess_type(self, path):  # correct types even on Windows registries
        p = str(path).lower()
        for ext, t in ((".js", "application/javascript"), (".css", "text/css"),
                       (".html", "text/html; charset=utf-8"), (".svg", "image/svg+xml")):
            if p.endswith(ext):
                return t
        return super().guess_type(path)

    def _send(self, data, ctype="application/json", code=200, headers=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _api(self, method):
        u = urlparse(self.path)
        route, q, E = u.path[5:].strip("/"), parse_qs(u.query), self.server.engine
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                return self._send(dict(error="Invalid JSON"), code=400)
        try:
            if method == "GET":
                if route == "state":
                    return self._send(E.state())
                if route == "health":
                    return self._send(E.gateway())
                if route == "settings":
                    return self._send(E.get_settings())
                if route == "snapshot":
                    return self._send(E.state()["reading"])
                if route == "history":
                    return self._send(E.history(float(q.get("hours", ["24"])[0])))
                if route == "export.csv":
                    name = "aquaguard_log_%s.csv" % time.strftime("%Y%m%d_%H%M%S")
                    return self._send(E.export_csv().encode("utf-8"), "text/csv; charset=utf-8",
                                      headers={"Content-Disposition": 'attachment; filename="%s"' % name})
            else:
                post = {
                    "simulate": lambda: E.simulate(body.get("scenario")),
                    "monitoring": lambda: E.set_monitoring(body.get("on")),
                    "purification": lambda: E.purification(body.get("cmd"), body.get("mode")),
                    "alerts": lambda: E.alert_action(body.get("action"), body.get("id")),
                    "settings": lambda: E.set_settings(body),
                    "reset": E.reset_session, "seed": E.seed, "wipe": E.wipe,
                }
                if route in post:
                    return self._send(post[route]())
        except Exception as exc:  # never crash the dashboard on a bad request
            return self._send(dict(error="Server error: %s" % exc), code=500)
        self._send(dict(error="Not found"), code=404)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._api("POST")
        self._send(dict(error="Not found"), code=404)


def serve(host="127.0.0.1", port=8000, open_browser=True):
    engine = Engine(STORE)
    httpd = None
    for p in list(range(port, port + 20)) + [0]:  # first free port
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("Could not open a network port.")
    httpd.engine, httpd.daemon_threads = engine, True
    url = "http://%s:%d/" % ("localhost" if host in ("127.0.0.1", "0.0.0.0") else host, httpd.server_address[1])

    def loop():
        while True:
            try:
                engine.tick()
            except Exception:
                pass
            time.sleep(1)

    threading.Thread(target=loop, daemon=True).start()
    print("=" * 56)
    print("  AquaGuard dashboard running at:  %s" % url)
    print("  Press Ctrl+C to stop.")
    print("=" * 56)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        engine.save()
        httpd.server_close()
