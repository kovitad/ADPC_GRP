"""Test a live JSON feed the way Global Risk's generic_json reader will (Share data, ADR-0052).

Global Risk fetches a contributed feed itself, once at submission and again on reads. Testing it
here first shows the person what Global Risk will see: whether the address is public, whether
the record list is there and not empty, and whether the records sort by the date field. The
logic mirrors ``SERVIR-AI/global-platform`` at ``a8a43c2``:

- ``contrib/fetch_policy.py``: http or https, no credentials, every address public, redirects
  re-checked;
- ``mcp/feeds.py`` ``_adapt_generic_json``: ``records_path`` and ``fields`` are dot paths
  (``a.0.b``), and rows are sorted on the *mapped* ``as_of_field``.

The fetch is pinned to the address that passed the check, so a name cannot answer a public
address to the check and a private one to the connection.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from core.contribution_rules import feed_url_problem

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(15.0, connect=10.0)
SAMPLE = 3


class FeedCheckError(Exception):
    """The feed could not be read; the message says why in plain words."""


def _public_address(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise FeedCheckError(f"The address {host} does not resolve.") from error
    addresses = sorted({info[4][0] for info in infos}, key=lambda a: ":" in a)
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise FeedCheckError(
                f"{host} points to a private address, which Global Risk will not fetch."
            )
    if not addresses:
        raise FeedCheckError(f"The address {host} does not resolve.")
    return addresses[0]


def fetch_json(url: str, client: httpx.Client | None = None) -> Any:
    """The parsed JSON at ``url``, fetched under the same rules as Global Risk."""

    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            problem = feed_url_problem(current)
            if problem:
                raise FeedCheckError(problem)
            parts = urlparse(current)
            address = _public_address(parts.hostname or "")
            host = f"[{address}]" if ":" in address else address
            port = f":{parts.port}" if parts.port else ""
            pinned = f"{parts.scheme}://{host}{port}{parts.path or '/'}"
            if parts.query:
                pinned += f"?{parts.query}"
            request = client.build_request(
                "GET", pinned,
                headers={"Host": parts.netloc, "Accept": "application/json"},
                extensions={"sni_hostname": parts.hostname} if parts.scheme == "https" else {},
            )
            response = client.send(request, stream=True)
            try:
                if 300 <= response.status_code < 400 and response.headers.get("location"):
                    current = urljoin(current, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise FeedCheckError(f"The feed answered HTTP {response.status_code}.")
                body = b""
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise FeedCheckError("The feed is larger than 5 MB.")
            finally:
                response.close()
            try:
                return json.loads(body.decode("utf-8-sig"))
            except (UnicodeDecodeError, ValueError) as error:
                raise FeedCheckError("The address did not return JSON.") from error
        raise FeedCheckError("The feed redirected too many times.")
    except httpx.HTTPError as error:
        raise FeedCheckError(f"The feed could not be reached ({type(error).__name__}).") from error
    finally:
        if own:
            client.close()


def dig(value: Any, path: str) -> Any:
    """A dot path into nested objects and lists, like Global Risk's ``_dig``."""

    current = value
    for part in str(path).split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def read_like_global_risk(document: Any, records_path: str, fields: dict[str, str],
                          as_of_field: str | None = None, limit: int = 12) -> dict[str, Any]:
    """What ``feeds_query`` would return for this document and mapping."""

    raw = dig(document, records_path)
    if not isinstance(raw, list) or not raw:
        raise FeedCheckError(
            f"No records at '{records_path}'. Global Risk treats an empty or missing list as a "
            "failure."
        )
    rows = [{name: dig(record, path) for name, path in fields.items()} for record in raw]
    sorted_by_time = False
    if as_of_field and all(row.get(as_of_field) is not None for row in rows):
        try:
            rows.sort(key=lambda row: (isinstance(row[as_of_field], str), row[as_of_field]))
            sorted_by_time = True
        except TypeError:
            pass
    tail = rows[-limit:]
    empty = [name for name in fields if all(row.get(name) is None for row in rows)]
    return {
        "count": len(rows),
        "returned_by_default": len(tail),
        "as_of": tail[-1].get(as_of_field) if as_of_field and tail else None,
        "sorted_by_time": sorted_by_time,
        "order": (f"sorted newest-last by {as_of_field}" if sorted_by_time
                  else "as published (no usable date field), so 'latest' is not guaranteed"),
        "empty_fields": empty,
        "first": rows[:SAMPLE],
        "last": tail[-SAMPLE:],
    }


def check_feed(url: str, records_path: str, fields: dict[str, str],
               as_of_field: str | None = None, client: httpx.Client | None = None) -> dict:
    """Fetch and read a feed. Never raises: a failure is ``ok: false`` with the reason."""

    try:
        result = read_like_global_risk(fetch_json(url, client), records_path, fields, as_of_field)
    except FeedCheckError as error:
        return {"ok": False, "problem": str(error)}
    notes = []
    if not result["sorted_by_time"]:
        notes.append("Map a date field and name it as the date field, so Global Risk returns "
                     "the newest records.")
    if result["empty_fields"]:
        notes.append("These fields were empty in every record: "
                     + ", ".join(result["empty_fields"]) + ". Check their paths.")
    return {"ok": True, **result, "notes": notes}
