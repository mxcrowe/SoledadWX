"""Receive screenshots from the barograph dev page and save them as PNG files.

A development aid: the web scene posts its own canvas here, so a web render
can be laid beside a Blender render at full resolution. Listens on localhost
only and writes only to ../renders/web/.

  python dev_shot_sink.py            (port 8765, or the PORT environment variable)
"""
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "renders" / "web"
NAME = re.compile(r"^[A-Za-z0-9_.-]+\.png$")


class Sink(BaseHTTPRequestHandler):
    def _reply(self, code, text=""):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode())

    def do_OPTIONS(self):
        self._reply(204)

    def do_GET(self):
        self._reply(200, "barograph screenshot sink")

    def do_POST(self):
        name = self.path.lstrip("/")
        if not NAME.match(name):
            self._reply(400, "bad name")
            return
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_bytes(data)
        self._reply(200, f"saved {name} ({len(data)} bytes)")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print(f"screenshot sink on http://127.0.0.1:{port} -> {OUT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Sink).serve_forever()
