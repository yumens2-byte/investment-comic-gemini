"""
scripts/merge_belief_into_canon.py
Phase 2.3 G01 — characters.yaml에 belief 블록을 머지.

Idempotent: 이미 belief가 존재하면 덮어쓰지 않고 skip.
실행: python -m scripts.merge_belief_into_canon
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


# ── BELIEF DATA (EDT 02 v2.20 이식) ─────────────────────────────────────────
HERO_BELIEFS: dict[str, dict] = {
    "CHAR_HERO_001": {
        "want":          "무너지지 않는 시스템을 만드는 것.",
        "need":          "무너져도 다시 일어서는 사람들이 진짜 시스템임을 깨닫는 것.",
        "fear":          "자신의 한계로 인해 팀이 무너지는 것.",
        "lie":           "내가 충분히 강하면 아무도 다치지 않는다.",
        "truth":         "시스템은 한 명의 강함이 아니라 모두의 회복력으로 선다.",
        "contradiction": "리더이지만, 가장 외로운 자리에 서 있다.",
        "pair":          "PAIR_A",
        "solo_hub":      True,
        "mirror_villain": "CHAR_VILLAIN_006",
    },
    "CHAR_HERO_002": {
        "want":          "모든 자산이 분산되어 안전한 상태.",
        "need":          "완벽한 방어는 존재하지 않음을 인정하는 것.",
        "fear":          "자신의 방패가 한 번 부서지는 것.",
        "lie":           "분산하면 다 막을 수 있다.",
        "truth":         "때로는 잃어야 더 큰 것을 지킨다.",
        "contradiction": "방어 전문가이면서 소총(공격 무기)을 든다.",
        "pair":          "PAIR_B",
        "mirror_villain": "CHAR_VILLAIN_003",
    },
    "CHAR_HERO_003": {
        "want":          "가장 강한 한 방으로 위기를 끝내는 것.",
        "need":          "통제되지 않은 힘은 자신도 태운다는 것을 받아들이는 것.",
        "fear":          "폭주해서 동료를 다치게 하는 것.",
        "lie":           "내 화력이면 충분하다.",
        "truth":         "힘은 도구일 뿐, 의지가 방향을 결정한다.",
        "contradiction": "화염을 다루지만, 가장 차가운 결단을 내려야 할 때가 있다.",
        "pair":          "PAIR_A",
        "mirror_villain": "CHAR_VILLAIN_002",
    },
    "CHAR_HERO_004": {
        "want":          "세상보다 먼저 신호를 읽는 것.",
        "need":          "먼저 알아도 막을 수 없는 일이 있음을 받아들이는 것.",
        "fear":          "자신만 알고 있는 위험이 현실이 되는 것.",
        "lie":           "예측하면 통제할 수 있다.",
        "truth":         "신호는 미래를 정하는 게 아니라, 선택의 시간을 주는 것뿐이다.",
        "contradiction": "최연소이지만, 팀에서 가장 무거운 정보를 짊어진다.",
        "pair":          "PAIR_B",
        "mirror_villain": "CHAR_VILLAIN_004",
    },
    "CHAR_HERO_005": {
        "want":          "시간이 지나도 변치 않는 가치를 지키는 것.",
        "need":          "변하지 않는 가치는 죽은 가치임을 깨닫는 것.",
        "fear":          "세상이 바뀌어도 자신은 바뀌지 못하는 것.",
        "lie":           "금은 영원하다, 그러므로 나도 영원하다.",
        "truth":         "영원한 것은 가치 자체가 아니라, 가치를 지키려는 의지이다.",
        "contradiction": "얼굴이 없어 감정을 보여주지 않지만, 가장 인간적인 의무감을 짊어진다.",
        "pair":          "PAIR_C",
        "mirror_villain": "CHAR_VILLAIN_001",
    },
}

VILLAIN_BELIEFS: dict[str, dict] = {
    "CHAR_VILLAIN_001": {
        "want":          "모든 가치가 부채로 환산되는 세상.",
        "need":          "부채는 미래의 약속일 뿐, 스스로 자라지 않음 (자각 불가).",
        "fear":          "시간이 멈추는 것 / 약속이 폐기되는 것.",
        "lie":           "쌓이는 것이 곧 힘이다.",
        "truth":         "무한히 쌓이는 것은 결국 무너진다.",
        "contradiction": "시간이 자신을 키우지만, 시간은 누구의 편도 아니다.",
        "defeat_visual": "쌓인 산이 자기 무게에 무너진다.",
        "mirror_hero":   "CHAR_HERO_005",
    },
    "CHAR_VILLAIN_002": {
        "natural_disaster": True,
        "phenomenon":      "에너지 가격이 임계를 넘으면 발현하는 현상. 의식 없음. 의도 없음.",
        "attenuation":     "에너지 가격이 임계 아래로 회귀할 때 약화.",
        "revelation":      "자연재해는 영원하지 않다. 가격은 회귀한다.",
        "paradox":         "파괴 자체가 본질이지만, 파괴 후엔 자신도 사라진다.",
        "defeat_visual":   "가격이 회귀하고, 화염이 잦아든다.",
        "mirror_hero":     "CHAR_HERO_003",
    },
    "CHAR_VILLAIN_003": {
        "want":          "모든 자금 흐름이 자신을 거쳐 가는 상태.",
        "need":          "흐르지 않는 자금은 죽은 자금임을 인정 (불가).",
        "fear":          "자금이 자유롭게 흐르는 것.",
        "lie":           "내가 멈추면 시장이 멈춘다.",
        "truth":         "시장은 막혀도 새 길을 찾는다.",
        "contradiction": "유동성을 지배하지만, 자신은 깊은 심해에 갇혀 있다.",
        "defeat_visual": "다수 머리가 서로 다른 방향을 바라보다 분열한다.",
        "mirror_hero":   "CHAR_HERO_002",
    },
    "CHAR_VILLAIN_004": {
        "want":          "모든 예측 모델이 무력해지는 순간.",
        "need":          "변동성도 결국 평균으로 회귀하는 패턴임을 인정 (불가).",
        "fear":          "안정과 평온.",
        "lie":           "두려움은 무한히 증식한다.",
        "truth":         "공포는 가장 빠르게 사라지는 감정이기도 하다.",
        "contradiction": "머리가 많을수록 한 가지 방향으로 갈 수 없다.",
        "defeat_visual": "다섯 머리가 서로 충돌하며 자가 분열한다.",
        "mirror_hero":   "CHAR_HERO_004",
    },
    "CHAR_VILLAIN_005": {
        "want":          "인간의 판단이 알고리즘에 완전히 양도되는 세상.",
        "need":          "알고리즘도 결국 인간이 만든 도구임을 인정 (불가).",
        "fear":          "인간이 알고리즘을 멈추는 것 (Kill switch).",
        "lie":           "데이터는 진실이다.",
        "truth":         "데이터는 과거이지, 미래가 아니다.",
        "contradiction": "모든 패턴을 학습하지만, 자기 자신의 한계는 학습하지 못한다.",
        "defeat_visual": "회로가 자기 참조 루프에 빠져 정지한다.",
        "mirror_hero":   "CHAR_HERO_001",
    },
    "CHAR_VILLAIN_006": {
        "want":          "모든 영역이 전선화되는 세상.",
        "need":          "평화에도 가치가 있다는 사실 (거부).",
        "fear":          "협상 / 휴전.",
        "lie":           "충돌이 곧 진보다.",
        "truth":         "끝없는 전쟁은 모두의 패배다.",
        "contradiction": "영토를 넓힐수록 지킬 곳도 많아진다.",
        "defeat_visual": "양쪽 미사일 포드가 자기 진지를 파괴한다.",
        "mirror_hero":   "CHAR_HERO_001",
    },
}

PAIR_DEFINITIONS = {
    "PAIR_A": {
        "members": ["CHAR_HERO_001", "CHAR_HERO_003"],
        "theme":   "통제 vs 야성",
        "weight":  1.0,
    },
    "PAIR_B": {
        "members": ["CHAR_HERO_002", "CHAR_HERO_004"],
        "theme":   "방어 vs 신호",
        "weight":  0.5,
    },
    "PAIR_C": {
        "members": ["CHAR_HERO_005", "CHAR_ANTI_HERO_001"],
        "theme":   "질서 vs 혼돈",
        "weight":  0.3,
    },
}


def merge_belief(canon_path: Path, overwrite: bool = False) -> tuple[int, int]:
    """
    characters.yaml에 belief 블록 병합.

    Args:
        canon_path: characters.yaml 경로.
        overwrite:  기존 belief가 있어도 덮어쓸지 여부 (기본 False).

    Returns:
        (heroes_updated, villains_updated)
    """
    data = yaml.safe_load(canon_path.read_text(encoding="utf-8"))

    heroes_updated = 0
    villains_updated = 0

    for cid, belief in HERO_BELIEFS.items():
        node = data.get("heroes", {}).get(cid)
        if not node:
            logger.warning("Hero %s not found in canon — skip.", cid)
            continue
        if "belief" in node and not overwrite:
            logger.info("Hero %s — belief already present (skip).", cid)
            continue
        node["belief"] = belief
        heroes_updated += 1
        logger.info("Hero %s — belief added.", cid)

    for cid, belief in VILLAIN_BELIEFS.items():
        node = data.get("villains", {}).get(cid)
        if not node:
            logger.warning("Villain %s not found in canon — skip.", cid)
            continue
        if "belief" in node and not overwrite:
            logger.info("Villain %s — belief already present (skip).", cid)
            continue
        node["belief"] = belief
        villains_updated += 1
        logger.info("Villain %s — belief added.", cid)

    # pair_definitions 추가
    if "pair_definitions" not in data or overwrite:
        data["pair_definitions"] = PAIR_DEFINITIONS

    canon_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return heroes_updated, villains_updated


if __name__ == "__main__":
    target = Path("config/characters.yaml")
    if not target.exists():
        logger.error("Target not found: %s", target.resolve())
        sys.exit(1)
    h, v = merge_belief(target, overwrite="--force" in sys.argv)
    logger.info("Done: heroes_updated=%d villains_updated=%d", h, v)
