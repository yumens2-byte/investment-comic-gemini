"""Diagnose whether the current Git branch can be updated/pushed.

This is an operator helper for GitHub rollout issues.  It checks the conditions
that commonly make `git pull`, `git push`, or branch update buttons fail:
missing remotes, missing upstream tracking branch, detached HEAD, and dirty worktree.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

GitRunner = Callable[[list[str]], tuple[int, str, str]]


@dataclass(frozen=True)
class BranchUpdateStatus:
    branch: str
    head: str
    remotes: tuple[str, ...]
    upstream: str
    dirty_files: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems


def _run_git(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _git_stdout(runner: GitRunner, args: list[str]) -> str:
    code, stdout, _stderr = runner(args)
    return stdout if code == 0 else ""


def collect_status(runner: GitRunner = _run_git) -> BranchUpdateStatus:
    branch = _git_stdout(runner, ["branch", "--show-current"])
    head = _git_stdout(runner, ["rev-parse", "HEAD"])
    remote_output = _git_stdout(runner, ["remote"])
    remotes = tuple(line.strip() for line in remote_output.splitlines() if line.strip())
    upstream = _git_stdout(runner, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    dirty_output = _git_stdout(runner, ["status", "--porcelain=v1"])
    dirty_files = tuple(line for line in dirty_output.splitlines() if line)

    problems: list[str] = []
    if not branch:
        problems.append("detached HEAD 상태입니다. 업데이트할 로컬 브랜치가 없습니다.")
    if not remotes:
        problems.append("Git remote가 없습니다. origin 등 원격 저장소가 설정되어야 합니다.")
    if remotes and not upstream:
        problems.append("현재 브랜치에 upstream 추적 브랜치가 없습니다.")
    if dirty_files:
        problems.append("커밋되지 않은 변경사항이 있어 안전한 업데이트 전 정리가 필요합니다.")

    return BranchUpdateStatus(
        branch=branch,
        head=head,
        remotes=remotes,
        upstream=upstream,
        dirty_files=dirty_files,
        problems=tuple(problems),
    )


def format_status(status: BranchUpdateStatus) -> str:
    lines = [
        "Git branch update readiness",
        f"- branch: {status.branch or '(none/detached)'}",
        f"- head: {status.head or '(unknown)'}",
        f"- remotes: {', '.join(status.remotes) if status.remotes else '(none)'}",
        f"- upstream: {status.upstream or '(none)'}",
        f"- dirty_files: {len(status.dirty_files)}",
    ]
    if status.ready:
        lines.append("- result: OK — branch update prerequisites are present.")
    else:
        lines.append("- result: BLOCKED")
        lines.extend(f"  - {problem}" for problem in status.problems)
    return "\n".join(lines)


def main() -> int:
    status = collect_status()
    print(format_status(status))
    return 0 if status.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
