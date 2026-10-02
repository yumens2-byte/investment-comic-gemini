"""Real postgrest-py request building against an in-memory HTTP transport.

Unlike attribute mocks, this builds the exact httpx request (URL, query, JSON body)
that production would send, so serialization and URL-length defects surface in tests.
"""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
from postgrest import SyncPostgrestClient

BASE_URL = "http://contract.invalid/rest/v1"
MAX_SAFE_URL = 8192


class CapturingClient:
    """Stands in for supabase.Client: `.schema(name)` returns a real postgrest client."""

    def __init__(self, responder: Callable[[httpx.Request], object]):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json=responder(request))

        transport = httpx.MockTransport(handler)
        self._postgrest = SyncPostgrestClient(
            BASE_URL, schema="icg",
            http_client=httpx.Client(transport=transport, base_url=BASE_URL),
        )

    def schema(self, _name: str) -> SyncPostgrestClient:
        return self._postgrest

    def table(self, name: str):
        return self._postgrest.table(name)


def body(request: httpx.Request) -> object:
    return json.loads(request.content or b"null")


def assert_request_shape(request: httpx.Request) -> None:
    """Fail on Python-repr filter values, oversized URLs and non-JSON bodies."""
    url = str(request.url)
    assert len(url) < MAX_SAFE_URL, f"request URL too long: {len(url)}"
    query = request.url.query.decode() if isinstance(request.url.query, bytes) else str(
        request.url.query)
    decoded = httpx.QueryParams(query)
    for key, value in decoded.multi_items():
        assert not value.startswith(("eq.{'", "neq.{'", "eq.['", "in.[")), (
            f"filter {key} uses a Python repr value")
        assert "None" not in value.split(".", 1)[-1:] , f"filter {key} sends None literal"
    if request.content:
        json.loads(request.content)  # body must be valid JSON
