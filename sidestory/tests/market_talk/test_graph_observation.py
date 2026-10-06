from __future__ import annotations

import pytest

from sidestory.adapters.facebook.graph import FacebookPagePublisher
from sidestory.ports.publisher import PublishError

SINCE = "2026-10-05T00:00:00+00:00"


def graph(pages):
    pub = FacebookPagePublisher("123", "fake-token")
    calls = []

    def call(method, path, **kwargs):
        calls.append((path, dict(kwargs["params"])))
        return pages.pop(0)

    pub._call = call
    return pub, calls


def test_pagination_uses_cursor_not_next_url():
    pub, calls = graph(
        [
            {
                "data": [{"id": "123_1", "created_time": "2026-10-05T03:00:00+0000"}],
                "paging": {
                    "next": "https://untrusted.example/token",
                    "cursors": {"after": "cursor1"},
                },
            },
            {"data": [{"id": "123_2", "created_time": "2026-10-06T03:00:00Z"}]},
        ]
    )
    assert len(pub.recent_receipts(SINCE)) == 2
    assert calls[1][0] == "123/feed" and calls[1][1]["after"] == "cursor1"


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": [{}]},
        {"data": [], "paging": {"next": "url"}},
        {"data": [{"id": "x", "created_time": "no"}]},
    ],
)
def test_incomplete_page_history_is_not_zero(response):
    pub, _ = graph([response])
    with pytest.raises(PublishError):
        pub.recent_receipts(SINCE)
