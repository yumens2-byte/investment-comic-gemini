from __future__ import annotations

from sidestory.core.models import ArcRow, MainEpisodeRow, MarketRow


def main_row(day: str = "2026-10-06", outcome: str = "HERO_VICTORY",
             scenario: str = "ONE_VS_ONE", no: int = 1) -> MainEpisodeRow:
    return MainEpisodeRow(
        episode_date=day,
        episode_no=no,
        event_type="BATTLE",
        scenario_type=scenario,
        heroes_json=["CHAR_HERO_002", "CHAR_HERO_001"],
        battle_json={"outcome": outcome, "villain_id": "CHAR_VILLAIN_001"},
        script_json={
            "title": "첨탑 아래의 방패",
            "logline": "금리의 첨탑 앞에서 방패가 버텼다",
            "panels": [
                {"idx": 6, "panel_type": "AFTERMATH", "narration": "첨탑은 아직 서 있다"},
                {"idx": 7, "panel_type": "TEXT_CARD", "narration": "오늘의 시장 인사이트"},
                {"idx": 8, "panel_type": "DISCLAIMER", "narration": "면책"},
            ],
            "_continuity": {
                "next_hook": "30년물이 다시 문을 두드린다",
                "unresolved_threads": ["첨탑의 균열은 어디서 시작됐나", "방패의 한계"],
            },
        },
    )


def market_row(day: str = "2026-10-06") -> MarketRow:
    return MarketRow(snapshot_date=day, us10y=5.24, vix=15.31, oil_wti=91.26,
                     spy_change=0.73, nasdaq_change=-0.42, dollar_index=101.92,
                     hy_spread=3.24, fear_greed=55.0)


def arc_row() -> ArcRow:
    return ArcRow(arc_day=16, arc_tension=87, hero_momentum=100,
                  active_villain="CHAR_VILLAIN_001", last_outcome="HERO_VICTORY",
                  last_episode_date="2026-10-06")


class FakeFeed:
    def __init__(self, rows, fingerprints=("a" * 64, "a" * 64)):
        self.rows = rows
        self._fps = list(fingerprints)
        self.calls = 0

    def published_episodes(self, start_date, end_date):
        return [r for r in self.rows if start_date <= r.episode_date <= end_date]

    def market(self, snapshot_date):
        return market_row(snapshot_date)

    def arc(self):
        return arc_row()

    def main_fingerprint(self, episode_date):
        value = self._fps[min(self.calls, len(self._fps) - 1)]
        self.calls += 1
        return value


class FakeStore:
    def __init__(self, anchored=None):
        self.anchored = set(anchored or [])
        self.episodes = {}
        self.logs = []

    def anchored_main_ids(self):
        return set(self.anchored)

    def upsert_episode(self, sid, fields):
        self.episodes[sid] = fields

    def get_episode(self, sid):
        return self.episodes.get(sid)

    def log(self, stage, status, detail):
        self.logs.append((stage, status, detail))
