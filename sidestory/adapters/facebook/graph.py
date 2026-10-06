"""Facebook Graph API Page publisher (P2).

Calls (Graph API, version from SIDESTORY_GRAPH_VERSION, default below):
  GET  /{page-id}?fields=id,name                       credential check
  POST /{page-id}/photos  source=<png>, published=false    unpublished photo → id
  POST /{page-id}/feed    message, attached_media[i]={"media_fbid": id}   → post id
  GET  /{page-id}/feed?fields=id,message&limit=N       reconcile an ambiguous post
  GET  /{post-id}?fields=id,permalink_url,created_time,is_published,message

The token is sent as a form/query field and is redacted from every error message.
Retries: none here. A feed POST that may have reached Facebook is reported as ambiguous.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from sidestory.ports.publisher import PublishError

# v26.0 released 2026-07-29 (developers.facebook.com/docs/graph-api/changelog/versions).
DEFAULT_VERSION = "v26.0"
TIMEOUT = (10, 60)          # connect, read (seconds)


class FacebookPagePublisher:
    channel = "facebook"

    def __init__(self, page_id: str, token: str, *, version: str | None = None,
                 session: Any = None):
        if not page_id or not token:
            raise PublishError("FACE_PAGE_ID / FACE_PAGE_TOKEN missing")
        self.page_id, self._token = page_id, token
        self.version = version or os.environ.get("SIDESTORY_GRAPH_VERSION", DEFAULT_VERSION)
        self._s = session or requests.Session()

    # ── helpers ─────────────────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return f"https://graph.facebook.com/{self.version}/{path}"

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    def _call(self, method: str, path: str, *, params=None, data=None, files=None,
              side_effect: bool) -> dict[str, Any]:
        try:
            if method == "GET":
                resp = self._s.get(self._url(path), params={**(params or {}),
                                                            "access_token": self._token},
                                   timeout=TIMEOUT)
            else:
                resp = self._s.post(self._url(path), data={**(data or {}),
                                                           "access_token": self._token},
                                    files=files, timeout=TIMEOUT)
        except requests.ConnectTimeout as exc:     # never reached Facebook
            raise PublishError(self._redact(f"connect timeout: {exc}")) from exc
        except requests.RequestException as exc:  # may have reached it
            raise PublishError(self._redact(f"{type(exc).__name__}: {exc}"),
                               ambiguous=side_effect) from exc
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code >= 400 or "error" in body:
            err = body.get("error") or {}
            msg = (f"HTTP {resp.status_code} code={err.get('code')} "
                   f"type={err.get('type')} {err.get('message', '')} "
                   f"fbtrace_id={err.get('fbtrace_id')}")
            # 5xx after a write may still have taken effect.
            raise PublishError(self._redact(msg), ambiguous=side_effect
                               and resp.status_code >= 500)
        return body

    # ── Publisher ───────────────────────────────────────────────────────────
    def check(self) -> dict[str, Any]:
        body = self._call("GET", self.page_id, params={"fields": "id,name"}, side_effect=False)
        if str(body.get("id")) != str(self.page_id):
            raise PublishError(f"token does not resolve to page {self.page_id}")
        return {"id": body.get("id"), "name": body.get("name")}

    def upload_photo(self, path: Path) -> str:
        with open(path, "rb") as fh:
            body = self._call("POST", f"{self.page_id}/photos",
                              data={"published": "false"},
                              files={"source": (Path(path).name, fh, "image/png")},
                              side_effect=False)   # unpublished: invisible even if duplicated
        if not body.get("id"):
            raise PublishError(f"photo upload returned no id for {Path(path).name}")
        return str(body["id"])

    def create_post(self, message: str, photo_ids: list[str]) -> str:
        data = {"message": message}
        for i, pid in enumerate(photo_ids):
            data[f"attached_media[{i}]"] = json.dumps({"media_fbid": pid})
        body = self._call("POST", f"{self.page_id}/feed", data=data, side_effect=True)
        if not body.get("id"):
            raise PublishError("post returned no id", ambiguous=True)
        return str(body["id"])

    def find_recent_post(self, message: str, limit: int = 10) -> str | None:
        body = self._call("GET", f"{self.page_id}/feed",
                          params={"fields": "id,message", "limit": str(limit)},
                          side_effect=False)
        for post in body.get("data") or []:
            if (post.get("message") or "").strip() == message.strip():
                return str(post["id"])
        return None

    def get_post(self, post_id: str) -> dict[str, Any]:
        return self._call("GET", post_id,
                          params={"fields": "id,permalink_url,created_time,is_published,message"},
                          side_effect=False)

    def recent_receipts(self, since: str) -> list[dict[str, str]]:
        """Bounded, paginated observation. Incomplete history blocks publication.

        Never follow a provider URL (which may contain access tokens); use only its
        cursor with the already configured Page endpoint.
        """
        from datetime import datetime

        cutoff = datetime.fromisoformat(since)
        params = {"fields": "id,created_time", "limit": "100", "since": str(int(cutoff.timestamp()))}
        receipts = []
        seen = set()
        for _ in range(10):
            body = self._call("GET", f"{self.page_id}/feed", params=params, side_effect=False)
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise PublishError("invalid Page history")
            for item in body["data"]:
                if not isinstance(item, dict) or not item.get("id") or not item.get("created_time"):
                    raise PublishError("incomplete Page receipt")
                try:
                    when = datetime.fromisoformat(item["created_time"].replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        raise ValueError("missing timezone")
                except (ValueError, TypeError, AttributeError):
                    raise PublishError("invalid Page receipt timestamp") from None
                if when >= cutoff:
                    receipts.append({"id": str(item["id"]), "created_time": when.isoformat()})
            paging = body.get("paging") or {}
            if not paging.get("next"):
                return receipts
            after = (paging.get("cursors") or {}).get("after")
            if not isinstance(after, str) or not after or after in seen:
                raise PublishError("incomplete Page pagination")
            seen.add(after)
            params["after"] = after
        raise PublishError("Page history exceeds bounded scan; operator review required")
