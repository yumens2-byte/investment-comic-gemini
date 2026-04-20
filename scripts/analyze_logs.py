"""Analyze ICG runtime/publish logs and generate an optimization-ready report.

Sources:
- output/episodes/*/run.log          (StepLogger JSONL)
- logs/*/*.log                       (video stage plain text)

Usage:
  python -m scripts.analyze_logs
  python -m scripts.analyze_logs --output output/log_analysis/report.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

STEP_RE = re.compile(r"\[(?P<step>STEP_[^\]]+)\]")


@dataclass
class JsonlSummary:
    files: int
    records: int
    levels: Counter
    steps: Counter
    failures: Counter
    durations: dict[str, list[int]]


@dataclass
class TextSummary:
    files: int
    lines: int
    level_hits: Counter
    stage_hits: Counter


def _read_jsonl_logs(base: Path) -> JsonlSummary:
    log_files = sorted(base.glob("output/episodes/*/run.log"))
    levels: Counter[str] = Counter()
    steps: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    durations: dict[str, list[int]] = defaultdict(list)
    records = 0

    for file in log_files:
        for line in file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            records += 1
            level = str(rec.get("level", "unknown"))
            step = str(rec.get("step", "unknown"))
            message = str(rec.get("message", ""))
            levels[level] += 1
            steps[step] += 1

            if level in {"warning", "error"} or "FAILED" in message:
                failures[step] += 1

            if isinstance(rec.get("duration_ms"), int):
                durations[step].append(int(rec["duration_ms"]))

    return JsonlSummary(
        files=len(log_files),
        records=records,
        levels=levels,
        steps=steps,
        failures=failures,
        durations=durations,
    )


def _read_text_logs(base: Path) -> TextSummary:
    log_files = sorted(base.glob("logs/*/*.log"))
    level_hits: Counter[str] = Counter()
    stage_hits: Counter[str] = Counter()
    lines_total = 0

    for file in log_files:
        for raw in file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line:
                continue
            lines_total += 1
            if "| ERROR |" in line:
                level_hits["error"] += 1
            elif "| WARNING |" in line:
                level_hits["warning"] += 1
            elif "| INFO |" in line:
                level_hits["info"] += 1
            m = STEP_RE.search(line)
            if m:
                stage_hits[m.group("step")] += 1

    return TextSummary(
        files=len(log_files),
        lines=lines_total,
        level_hits=level_hits,
        stage_hits=stage_hits,
    )


def _fmt_top(counter: Counter, n: int = 5) -> str:
    if not counter:
        return "- (없음)"
    return "\n".join(f"- {k}: {v}" for k, v in counter.most_common(n))


def _duration_block(durations: dict[str, list[int]]) -> str:
    if not durations:
        return "- (duration_ms 데이터 없음)"

    lines: list[str] = []
    for step, values in sorted(durations.items()):
        vals = sorted(values)
        p95_idx = int(len(vals) * 0.95) - 1
        p95_idx = max(0, min(p95_idx, len(vals) - 1))
        lines.append(
            f"- {step}: count={len(vals)}, p50={int(median(vals))}ms, p95={vals[p95_idx]}ms, max={vals[-1]}ms"
        )
    return "\n".join(lines)


def build_report(base: Path) -> str:
    js = _read_jsonl_logs(base)
    tx = _read_text_logs(base)

    recommendations: list[str] = []
    if js.files == 0 and tx.files == 0:
        recommendations.append("로그 파일이 없어 런타임 기반 병목 분석이 불가합니다. 스케줄 실행 산출물(run.log, stage.log) 아카이빙을 먼저 강제하세요.")
    if js.levels.get("error", 0) > 0:
        recommendations.append("error 로그가 존재합니다. STEP 단위로 재시도 가능/불가능 오류를 분리하고 알림 우선순위를 나누세요.")
    if js.records > 0 and not js.durations:
        recommendations.append("duration_ms 누락 스텝이 많습니다. 모든 주요 스텝을 step_start/step_done으로 감싸 SLO 측정 가능 상태로 전환하세요.")
    if tx.files > 0:
        recommendations.append("video 로그는 plain text 포맷입니다. StepLogger(JSONL) 호환 이벤트를 병행 기록해 트랙 간 통합 대시보드를 구성하세요.")
    if not recommendations:
        recommendations.append("현재 데이터 기준 큰 이상은 보이지 않습니다. 실패 상위 STEP에 대해 자동 리커버리 정책을 추가 검토하세요.")

    return f"""# ICG 로그 분석 리포트

## 1) 수집 범위
- JSONL run logs: {js.files} files / {js.records} records
- Video stage text logs: {tx.files} files / {tx.lines} lines

## 2) StepLogger(JSONL) 요약
### Level 분포
{_fmt_top(js.levels, n=10)}

### STEP 호출 빈도
{_fmt_top(js.steps, n=15)}

### 실패/경고 집중 STEP
{_fmt_top(js.failures, n=10)}

### Duration 분포 (step별)
{_duration_block(js.durations)}

## 3) Video plain-text 로그 요약
### Level 히트
{_fmt_top(tx.level_hits, n=10)}

### STEP 토큰 히트
{_fmt_top(tx.stage_hits, n=15)}

## 4) 고도화 설계 제안
""" + "\n".join(f"- {r}" for r in recommendations) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ICG 로그 분석 리포트 생성")
    parser.add_argument("--base", default=".", help="리포지토리 루트 경로")
    parser.add_argument(
        "--output",
        default="output/log_analysis/report.md",
        help="출력 마크다운 경로",
    )
    args = parser.parse_args(argv)

    base = Path(args.base).resolve()
    report = build_report(base)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[analyze_logs] report written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
