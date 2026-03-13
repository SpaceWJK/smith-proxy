"""GDI S3 File Manager — Local Proxy Server

CORS 제약 우회를 위한 로컬 프록시.
s3_manager.html을 서빙하고 GDI API 호출을 프록시합니다.

사용법:
  python s3_server.py          # http://localhost:9090
  python s3_server.py --port 8080
"""
import http.server
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import sys
import argparse
import mimetypes
from io import BytesIO

GDI_API = (
    "http://k8s-llmopsalbgroup-2f93202457-431440703"
    ".ap-northeast-1.elb.amazonaws.com/game-doc-insight-ui/api"
)
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server + GDI API reverse proxy."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    # ── API proxy ───────────────────────────────────────────
    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy_get()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy_post()
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    # ── Proxy internals ─────────────────────────────────────
    def _proxy_get(self):
        api_path = self.path[len("/api"):]  # strip /api prefix
        url = GDI_API + api_path
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", len(data))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._error_json(502, str(e))

    def _proxy_post(self):
        api_path = self.path[len("/api"):]
        url = GDI_API + api_path
        content_length = int(self.headers.get("Content-Length", 0))
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(content_length) if content_length else b""

        try:
            req = urllib.request.Request(url, data=body, method="POST")
            if content_type:
                req.add_header("Content-Type", content_type)
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_type = resp.headers.get("Content-Type", "application/json")
                data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp_type)
                self.send_header("Content-Length", len(data))
                self._cors_headers()
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._error_json(502, str(e))

    # ── Helpers ──────────────────────────────────────────────
    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _error_json(self, code, msg):
        body = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quieter logging
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write(f"[proxy] {args[0]}\n")


def main():
    parser = argparse.ArgumentParser(description="GDI S3 File Manager")
    parser.add_argument("--port", type=int, default=9090)
    args = parser.parse_args()

    server = http.server.HTTPServer(("0.0.0.0", args.port), ProxyHandler)
    print(f"GDI S3 File Manager → http://localhost:{args.port}/s3_manager.html")
    print(f"GDI API proxy       → http://localhost:{args.port}/api/*")
    print("Press Ctrl+C to stop")

    import webbrowser
    webbrowser.open(f"http://localhost:{args.port}/s3_manager.html")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
