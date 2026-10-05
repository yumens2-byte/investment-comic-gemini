"""8-panel beat map per outcome class (P1 design §2-2, approved D-P1-2).

Panels 1–6 are written by the LLM; 7 (data card) and 8 (disclaimer) are built
deterministically from the EchoPack so no model-written number reaches them.
"""
from __future__ import annotations

from dataclasses import dataclass

from sidestory.core.models import OutcomeClass

POSES = ("front", "side", "back", "attack", "defense", "none")
SILHOUETTE_KEYS = ("node_a", "node_b", "node_c")
STORY_PANEL_TYPES = ("COVER", "TENSION", "CLIMAX", "AFTERMATH")
LLM_PANELS = 6
TOTAL_PANELS = 8


@dataclass(frozen=True)
class PanelBeat:
    idx: int
    panel_type: str
    beat: str
    allowed_poses: tuple[str, ...] = POSES
    max_silhouettes: int = 0
    must_cite_main: bool = False


_COVER = {
    OutcomeClass.VICTORY: "승리 직후의 도시, 멀리서 지켜보는 관찰자의 실루엣",
    OutcomeClass.DRAW: "맞선 두 힘이 남긴 잔광이 떠 있는 하늘",
    OutcomeClass.DEFEAT: "균열이 번진 스카이라인",
    OutcomeClass.NO_BATTLE: "고요하게 흐르는 데이터의 강",
}
_FLOW = {
    OutcomeClass.VICTORY: "물러난 빌런이 남긴 붕괴 데이터가 어딘가로 흘러간다",
    OutcomeClass.DRAW: "어느 쪽도 회수하지 못한 데이터가 공중에 떠 있다",
    OutcomeClass.DEFEAT: "붕괴 데이터가 급증해 도시 위로 쏟아진다",
    OutcomeClass.NO_BATTLE: "수치들 사이의 간극(공포·탐욕 등)에서 미세한 균열 징후가 보인다",
}
_OBSERVE = {
    OutcomeClass.VICTORY: ("Zero Block이 흐름을 관찰·기록한다(전투 자세 금지)",
                           ("front", "side", "back")),
    OutcomeClass.DRAW: ("Zero Block이 균형의 틈을 관찰·측정한다", ("front", "side", "back")),
    OutcomeClass.DEFEAT: ("Zero Block은 개입하지 않고 방어 자세로 기록만 한다", ("defense",)),
    OutcomeClass.NO_BATTLE: ("Zero Block이 다음 균열의 징후를 탐색한다",
                             ("front", "side", "back")),
}


def beats_for(outcome_class: OutcomeClass) -> list[PanelBeat]:
    observe, observe_poses = _OBSERVE[outcome_class]
    return [
        PanelBeat(1, "COVER", _COVER[outcome_class]),
        PanelBeat(2, "TENSION", "본편 회차를 인용한다(제목·결과는 key_text/narration 글자로만, 변경 금지). "
                  "그림은 본편 전투가 남긴 추상적 잔향(빛·파편)이며 글자 형상 금지",
                  must_cite_main=True),
        PanelBeat(3, "TENSION", _FLOW[outcome_class]),
        PanelBeat(4, "CLIMAX", observe, allowed_poses=observe_poses),
        PanelBeat(5, "CLIMAX", "원경에 노드가 존재함을 암시(이름·대사 없음). 노드는 silhouettes 항목에 키만 "
                  "지정하고, setting/action은 풍경만 영어로 묘사 "
                  "(예: 'a fractured data plain under a dim horizon')",
                  max_silhouettes=2 if outcome_class is OutcomeClass.DEFEAT else 1),
        PanelBeat(6, "AFTERMATH", "Zero Block 독백(시스템·구조 비판, 냉정한 관찰자) + 다음 외전 훅"),
    ]
