"""The feed-only relay exposes /feed.json and nothing else (ADR-0052)."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from grpcli.feed_relay import make_handler


class Upstream(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("If-None-Match") == '"abc"':
            self.send_response(304)
            self.send_header("ETag", '"abc"')
            self.end_headers()
            return
        self.send_response(Upstream.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", '"abc"')
        self.send_header("Cache-Control", "public, max-age=60")
        self.send_header("Set-Cookie", "grp_session=secret")
        self.end_headers()
        self.wfile.write(b'{"districts": []}')

    def log_message(self, *_args) -> None:
        pass


def _serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def relay():
    Upstream.status = 200
    upstream, upstream_url = _serve(Upstream)
    server, url = _serve(make_handler(f"{upstream_url}/api/v1/public/flood/bangkok/feed.json"))
    yield url
    server.shutdown()
    upstream.shutdown()


def _get(url: str, **headers) -> tuple[int, dict, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as reply:
            return reply.status, dict(reply.headers), reply.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_only_the_feed_path_is_served(relay) -> None:
    status, headers, body = _get(f"{relay}/feed.json")
    assert status == 200 and body == b'{"districts": []}'
    assert headers["ETag"] == '"abc"' and "Set-Cookie" not in headers
    for path in ("/", "/api/v1/me", "/admin", "/feed.json/../api/v1/me", "/planning.html"):
        assert _get(f"{relay}{path}")[0] == 404


def test_not_modified_passes_through(relay) -> None:
    assert _get(f"{relay}/feed.json", **{"If-None-Match": '"abc"'})[0] == 304


def test_a_switched_off_feed_is_not_found(relay) -> None:
    Upstream.status = 404
    status, _headers, body = _get(f"{relay}/feed.json")
    assert status == 404 and body == b"feed unavailable"
