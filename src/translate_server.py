"""HTTP translation server for browser extensions.

Runs on 127.0.0.1:19378 in a daemon thread. Provides /translate endpoint
with bearer-token auth for browser extensions to call TranslateEngine.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from .config import APP_DIR, APP_VERSION
from .translate_engine import TranslateEngine

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 50


class TranslateServer:
    """HTTP server exposing TranslateEngine to browser extensions."""

    def __init__(self, translate_engine: TranslateEngine, port: int = 19378):
        self._engine = translate_engine
        self._port = port
        self._token: str | None = None
        self._token_issued = False
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the HTTP server in a daemon thread."""
        handler = partial(_Handler, self)
        self._server = HTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="TranslateServer",
            daemon=True,
        )
        self._thread.start()
        logger.info("Translation server started on 127.0.0.1:%d", self._port)

    def stop(self) -> None:
        """Shut down the server."""
        if self._server:
            self._server.shutdown()
            logger.info("Translation server stopped")

    def issue_token(self) -> str:
        """Issue a bearer token. Re-issues a new token on each call."""
        self._token = secrets.token_hex(32)
        self._token_issued = True
        return self._token

    def verify_token(self, token: str) -> bool:
        """Check if the provided token matches the issued one."""
        return self._token is not None and secrets.compare_digest(self._token, token)


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler for the translation server."""

    def __init__(self, server_instance: TranslateServer, *args, **kwargs):
        self._ts = server_instance
        super().__init__(*args, **kwargs)

    # ── Silence default logging ──────────────────────────────────────
    def log_message(self, format, *args):
        logger.debug("HTTP %s", format % args)

    # ── CORS helpers ─────────────────────────────────────────────────
    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json_response(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._set_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file_response(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self._json_response(404, {"error": "file not found"})
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self._set_cors_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── Auth helper ──────────────────────────────────────────────────
    def _check_auth(self) -> bool:
        """Validate bearer token. Sends 401/403 and returns False on failure."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._json_response(401, {"error": "missing Authorization header"})
            return False
        token = auth[7:]
        if not self._ts.verify_token(token):
            self._json_response(403, {"error": "invalid token"})
            return False
        return True

    # ── Routes ───────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._json_response(200, {"status": "ok", "version": APP_VERSION})

        elif self.path == "/token":
            token = self._ts.issue_token()
            self._json_response(200, {"token": token})

        elif self.path == "/extension/update.xml":
            # Stub — will be finished in Task 5
            port = self._ts._port
            ns = "http://www.google.com/update2/response"
            base = f"http://127.0.0.1:{port}"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<gupdate xmlns="{ns}" protocol="2.0">\n'
                '  <app appid="ai-polyglot-kit">\n'
                f"    <updatecheck"
                f' codebase="{base}/extension/apk.crx"'
                f' version="{APP_VERSION}" />\n'
                "  </app>\n"
                "</gupdate>"
            )
            body = xml.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self._set_cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/extension/apk.crx":
            crx_path = APP_DIR / "extension" / "apk.crx"
            self._file_response(crx_path, "application/x-chrome-extension")

        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/translate":
            if not self._check_auth():
                return

            # Read body
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._json_response(400, {"error": "empty body"})
                return

            try:
                raw = self.rfile.read(content_length)
                payload = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as e:
                self._json_response(400, {"error": f"invalid JSON: {e}"})
                return

            texts = payload.get("texts")
            if not isinstance(texts, list) or not texts:
                self._json_response(400, {"error": "'texts' must be a non-empty list"})
                return

            if len(texts) > MAX_BATCH_SIZE:
                self._json_response(
                    400, {"error": f"max {MAX_BATCH_SIZE} texts per batch"}
                )
                return

            target_lang = payload.get("target_lang") or payload.get("lang") or "uk"
            source_lang = payload.get("source_lang", "auto")

            try:
                translations, engine = self._ts._engine.translate_batch(
                    texts, target_lang, source_lang
                )
                self._json_response(200, {
                    "translations": translations,
                    "engine": engine,
                })
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                logger.debug("Client disconnected before response was sent")
            except Exception as e:
                logger.exception("Translation failed")
                try:
                    self._json_response(500, {"error": str(e)})
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    logger.debug("Client disconnected during error response")

        else:
            self._json_response(404, {"error": "not found"})
