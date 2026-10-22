"""Servidor HTTP local: API JSON + app movil React (web/dist) para controlar desde el celular."""
from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..application.controller import AppController


def lan_ip() -> str:
    """IP de esta PC en la red local (la que usa el celular)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envia nada, solo elige interfaz
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class WebServer:
    def __init__(self, controller: AppController, static_dir: str, port: int, token: str):
        self.controller = controller
        self.static_dir = os.path.abspath(static_dir)
        self.port = port
        self.token = token
        self.httpd: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}/?t={self.token}"

    def _watch_ip(self):
        """Mantiene server_url al dia si la PC cambia de IP (otra red, DHCP)."""
        while self.httpd:
            self.controller.server_url = self.url
            time.sleep(5)

    def start(self) -> str:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencio en consola
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def _authorized(self, qs) -> bool:
                tok = self.headers.get("X-Token") or (qs.get("t") or [""])[0]
                return tok == server.token

            def do_GET(self):
                u = urlparse(self.path)
                qs = parse_qs(u.query)
                if u.path.startswith("/api/"):
                    if not self._authorized(qs):
                        return self._json({"error": "token invalido"}, 401)
                    if u.path == "/api/state":
                        since = int((qs.get("since") or ["0"])[0])
                        return self._json(server.controller.state(since))
                    return self._json({"error": "no existe"}, 404)
                self._static(u.path)

            def do_POST(self):
                u = urlparse(self.path)
                if not self._authorized(parse_qs(u.query)):
                    return self._json({"error": "token invalido"}, 401)
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                    c = server.controller
                    if u.path == "/api/start":
                        c.start(body.get("profile"), body.get("url"))
                    elif u.path == "/api/stop":
                        c.stop()
                    elif u.path == "/api/command":
                        c.command(body["name"], **body.get("args", {}))
                    elif u.path == "/api/profile":
                        c.set_active(body["name"])
                    elif u.path == "/api/quality":
                        c.set_quality(bool(body.get("enabled")))
                    elif u.path == "/api/limit":
                        c.set_limit(bool(body.get("enabled")), int(body.get("count", 3)))
                    else:
                        return self._json({"error": "no existe"}, 404)
                    self._json({"ok": True})
                except Exception as e:  # noqa: BLE001
                    self._json({"error": str(e)}, 400)

            def _static(self, path: str):
                rel = path.lstrip("/") or "index.html"
                full = os.path.abspath(os.path.join(server.static_dir, rel))
                if not full.startswith(server.static_dir) or not os.path.isfile(full):
                    full = os.path.join(server.static_dir, "index.html")  # SPA
                if not os.path.isfile(full):
                    return self._send(503, "Falta compilar la app movil: cd web && npm run build".encode(), "text/plain; charset=utf-8")
                with open(full, "rb") as f:
                    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                    self._send(200, f.read(), ctype)

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.controller.server_url = self.url
        threading.Thread(target=self._watch_ip, daemon=True).start()
        return self.url

    def stop(self):
        if self.httpd:
            httpd, self.httpd = self.httpd, None
            httpd.shutdown()
