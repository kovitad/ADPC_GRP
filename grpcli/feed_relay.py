"""Serve only the public live flood feed, so a tunnel can expose it and nothing else (ADR-0052).

The GRP API stays on 127.0.0.1:8000 with sign-in, Admin and every other route. This relay listens
on its own port and answers exactly one path, ``/feed.json``, by reading the API's anonymous feed
route (switched on with ``FLOOD_FEED_PUBLIC=true``). Everything else is 404. Put the tunnel in
front of this port, never in front of the API.

    python -m grpcli.feed_relay --port 8090
"""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATHS = ("/feed.json", "/bangkok/feed.json")
PASS_HEADERS = ("ETag", "Cache-Control", "Content-Type")


def make_handler(upstream: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "grp-feed-relay"
        sys_version = ""

        def _answer(self, with_body: bool) -> None:
            if self.path.split("?", 1)[0] not in PATHS:
                self._plain(404, b"not found", with_body)
                return
            request = urllib.request.Request(upstream, headers={"Accept": "application/json"})
            if self.headers.get("If-None-Match"):
                request.add_header("If-None-Match", self.headers["If-None-Match"])
            try:
                with urllib.request.urlopen(request, timeout=20) as reply:
                    body, status, headers = reply.read(), reply.status, reply.headers
            except urllib.error.HTTPError as error:
                if error.code == 304:
                    self.send_response(304)
                    for name in PASS_HEADERS[:2]:
                        if error.headers.get(name):
                            self.send_header(name, error.headers[name])
                    self.end_headers()
                    return
                # 404 means the public feed is switched off: say so without detail.
                self._plain(404 if error.code == 404 else 502, b"feed unavailable", with_body)
                return
            except (urllib.error.URLError, TimeoutError):
                self._plain(502, b"feed unavailable", with_body)
                return
            self.send_response(status)
            for name in PASS_HEADERS:
                if headers.get(name):
                    self.send_header(name, headers[name])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if with_body:
                self.wfile.write(body)

        def _plain(self, status: int, text: bytes, with_body: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(text)))
            self.end_headers()
            if with_body:
                self.wfile.write(text)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._answer(True)

        def do_HEAD(self) -> None:  # noqa: N802 - http.server API
            self._answer(False)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - http.server API
            # One line per request, no client addresses kept beyond the console.
            print(f"{self.log_date_time_string()} {self.command} {self.path} -> {args[1]}")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--pilot", default="bangkok")
    args = parser.parse_args(argv)
    upstream = f"{args.api}/api/v1/public/flood/{args.pilot}/feed.json"
    server = ThreadingHTTPServer((args.host, args.port), make_handler(upstream))
    print(f"Serving {upstream} as http://{args.host}:{args.port}/feed.json (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
