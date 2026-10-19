"""Resolve an available episode artifact for read-only assembly replay."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import requests


def select_source(rows: list[dict], artifacts_for_run) -> dict:
    for row in rows:
        day = row.get("episode_date", "")
        number = row.get("episode_no")
        run = str(row.get("artifact_run_id") or "")
        if not re.fullmatch(r"[0-9]+", run) or type(number) is not int or not 1 <= number <= 999:
            continue
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Invalid source date")
        episode = f"ICG-{day}-{number:03d}"
        script = row.get("script_json")
        if (
            not isinstance(script, dict)
            or script.get("episode_id") != episode
            or script.get("date") != day
        ):
            raise ValueError("Source narrative identity mismatch")
        matches = [
            a
            for a in artifacts_for_run(run)
            if a.get("name") == f"episode-{run}" and a.get("expired") is False
        ]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("Ambiguous source artifact")
        return {"episode_id": episode, "run_id": run, "script": script}
    raise RuntimeError("No available episode artifact for assembly replay")


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    base = os.environ["SUPABASE_URL"].rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not base.startswith(
        "https://"
    ):
        raise ValueError("Invalid configured service identity")
    key = os.environ["SUPABASE_KEY"]
    response = requests.get(
        base + "/rest/v1/episode_assets",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "icg"},
        params={
            "select": "episode_date,episode_no,artifact_run_id,script_json",
            "status": "in.(image_generated,assembled,published)",
            "order": "episode_date.desc,episode_no.desc",
            "limit": "20",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Source lookup failed: HTTP {response.status_code}")
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("Invalid episode lookup response")

    def artifacts(run):
        result = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs/{run}/artifacts",
            headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100},
            timeout=30,
        )
        if result.status_code == 404:
            return []
        if result.status_code != 200:
            raise RuntimeError(f"Artifact lookup failed: HTTP {result.status_code}")
        return result.json()["artifacts"]

    source = select_source(rows, artifacts)
    destination = Path(os.environ["RUNNER_TEMP"]) / "assembly-beta-source.json"
    with destination.open("x", encoding="utf-8") as handle:
        destination.chmod(0o600)
        json.dump(source["script"], handle, ensure_ascii=False)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as handle:
        handle.write(f"episode_id={source['episode_id']}\nrun_id={source['run_id']}\n")
    print(
        json.dumps(
            {
                "episode_id": source["episode_id"],
                "run_id": source["run_id"],
                "database_writes": 0,
                "paid_calls": 0,
                "publishes": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
