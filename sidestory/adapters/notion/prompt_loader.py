"""Load the side system prompt from a Notion page (NOTION_SIDE_SYSTEM_ID).

Independent of engine.common.notion_loader (split readiness). Paginates, and reads
paragraph / heading / list / quote / code blocks as plain text.
"""
from __future__ import annotations

import os

import requests

from sidestory.ports.llm import LLMError

_API = "https://api.notion.com/v1"
_TEXT_BLOCKS = {"paragraph", "heading_1", "heading_2", "heading_3", "quote", "code",
                "bulleted_list_item", "numbered_list_item", "callout", "toggle"}
MIN_PROMPT_CHARS = 200


def blocks_to_text(blocks: list[dict]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        btype = block.get("type", "")
        if btype not in _TEXT_BLOCKS:
            continue
        text = "".join(r.get("plain_text", "") for r in block.get(btype, {}).get("rich_text", []))
        if btype == "bulleted_list_item":
            text = f"- {text}"
        elif btype == "numbered_list_item":
            text = f"1. {text}"
        elif btype.startswith("heading_"):
            text = "#" * int(btype[-1]) + f" {text}"
        if text.strip() or btype == "code":
            lines.append(text)
    return lines


class NotionPromptSource:
    def __init__(self, page_id: str | None = None, token: str | None = None, session=None):
        self.page_id = (page_id or os.environ.get("NOTION_SIDE_SYSTEM_ID", "")).replace("-", "")
        self.token = token or os.environ.get("NOTION_API_KEY", "")
        self._http = session or requests

    def system_prompt(self) -> str:
        if not self.page_id or not self.token:
            raise LLMError("NOTION_SIDE_SYSTEM_ID / NOTION_API_KEY missing")
        headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": "2022-06-28"}
        lines: list[str] = []
        cursor = None
        for _ in range(20):  # ≤2,000 blocks
            url = f"{_API}/blocks/{self.page_id}/children?page_size=100"
            if cursor:
                url += f"&start_cursor={cursor}"
            resp = self._http.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                raise LLMError(f"Notion prompt load failed: HTTP {resp.status_code}")
            body = resp.json()
            lines += blocks_to_text(body.get("results", []))
            if not body.get("has_more"):
                break
            cursor = body.get("next_cursor")
        text = "\n".join(lines).strip()
        if len(text) < MIN_PROMPT_CHARS:
            raise LLMError(f"Notion side system prompt too short ({len(text)} chars)")
        return text
