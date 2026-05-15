"""
Phase 2.3 G01 — characters.yaml BELIEF Sheet 머지 검증.

검증 항목:
- 5명 히어로 belief 6요소 (want/need/fear/lie/truth/contradiction)
- 6명 빌런 belief
- V002 Oil Shock Titan = natural_disaster 4요소 (phenomenon/attenuation/revelation/paradox)
- pair_definitions 존재 (PAIR_A/B/C)
- mirror_villain / mirror_hero 양방향 매핑
- Idempotent: 두 번 호출해도 중복 추가 없음
- overwrite=False 기본값에서 기존 belief 유지
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from scripts.merge_belief_into_canon import (
    HERO_BELIEFS,
    PAIR_DEFINITIONS,
    VILLAIN_BELIEFS,
    merge_belief,
)


@pytest.fixture
def temp_canon(tmp_path: Path) -> Path:
    """기존 characters.yaml을 임시 디렉토리에 복사."""
    src = Path("config/characters.yaml")
    if not src.exists():
        pytest.skip("config/characters.yaml not found")
    dst = tmp_path / "characters.yaml"
    shutil.copyfile(src, dst)
    return dst


# ── 머지 동작 ─────────────────────────────────────────────────────────────────

def test_merge_belief_first_run(temp_canon: Path) -> None:
    """첫 실행: 5 히어로 + 6 빌런 모두 추가."""
    h, v = merge_belief(temp_canon, overwrite=False)
    # 기존 canon에 belief가 없다면 5/6, 이미 있다면 0/0
    data = yaml.safe_load(temp_canon.read_text(encoding="utf-8"))
    for cid in HERO_BELIEFS:
        assert "belief" in data["heroes"][cid], f"{cid} belief missing"
    for cid in VILLAIN_BELIEFS:
        assert "belief" in data["villains"][cid], f"{cid} belief missing"


def test_merge_belief_idempotent(temp_canon: Path) -> None:
    """두 번 호출해도 동일 결과 (overwrite=False)."""
    merge_belief(temp_canon, overwrite=False)
    first = temp_canon.read_text(encoding="utf-8")
    h2, v2 = merge_belief(temp_canon, overwrite=False)
    second = temp_canon.read_text(encoding="utf-8")
    assert h2 == 0, "이미 belief 있는 히어로는 재추가 금지"
    assert v2 == 0, "이미 belief 있는 빌런은 재추가 금지"
    assert first == second, "내용이 변하면 안 됨"


# ── 6요소 검증 (HERO) ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "char_id",
    ["CHAR_HERO_001", "CHAR_HERO_002", "CHAR_HERO_003", "CHAR_HERO_004", "CHAR_HERO_005"],
)
def test_hero_belief_has_6_elements(temp_canon: Path, char_id: str) -> None:
    merge_belief(temp_canon, overwrite=False)
    data = yaml.safe_load(temp_canon.read_text(encoding="utf-8"))
    belief = data["heroes"][char_id]["belief"]
    required = {"want", "need", "fear", "lie", "truth", "contradiction"}
    assert required.issubset(belief.keys()), (
        f"{char_id} missing {required - belief.keys()}"
    )
    # 각 요소 비어있지 않음
    for key in required:
        assert belief[key], f"{char_id}.{key} is empty"


def test_hero_belief_has_pair_field(temp_canon: Path) -> None:
    """각 히어로 belief에 pair 정보 포함."""
    merge_belief(temp_canon, overwrite=False)
    data = yaml.safe_load(temp_canon.read_text(encoding="utf-8"))
    expected_pairs = {
        "CHAR_HERO_001": "PAIR_A",
        "CHAR_HERO_002": "PAIR_B",
        "CHAR_HERO_003": "PAIR_A",
        "CHAR_HERO_004": "PAIR_B",
        "CHAR_HERO_005": "PAIR_C",
    }
    for cid, expected in expected_pairs.items():
        assert data["heroes"][cid]["belief"]["pair"] == expected


# ── Natural Disaster (V002 Oil Shock Titan) ───────────────────────────────────

def test_v002_oil_shock_natural_disaster(temp_canon: Path) -> None:
    """V002는 belief 6요소 대신 자연재해 4요소 (phenomenon/attenuation/revelation/paradox)."""
    merge_belief(temp_canon, overwrite=False)
    data = yaml.safe_load(temp_canon.read_text(encoding="utf-8"))
    belief = data["villains"]["CHAR_VILLAIN_002"]["belief"]
    assert belief.get("natural_disaster") is True
    required = {"phenomenon", "attenuation", "revelation", "paradox"}
    assert required.issubset(belief.keys()), (
        f"V002 missing natural_disaster fields {required - belief.keys()}"
    )
    # 의도/욕망 필드는 없어야 함 (의식 없는 자연재해)
    assert "want" not in belief
    assert "need" not in belief


# ── 6요소 검증 (VILLAIN — V002 제외) ──────────────────────────────────────────

@pytest.mark.parametrize(
    "char_id",
    ["CHAR_VILLAIN_001", "CHAR_VILLAIN_003", "CHAR_VILLAIN_004",
     "CHAR_VILLAIN_005", "CHAR_VILLAIN_006"],
)
def test_villain_belief_has_full_elements(temp_canon: Path, char_id: str) -> None:
    merge_belief(temp_canon, overwrite=False)
    data = yaml.safe_load(temp_canon.read_text(encoding="utf-8"))
    belief = data["villains"][char_id]["belief"]
    required = {"want", "lie", "truth", "contradiction", "defeat_visual"}
    assert required.issubset(belief.keys()), (
        f"{char_id} missing {required - belief.keys()}"
    )


# ── pair_definitions ──────────────────────────────────────────────────────────

def test_pair_definitions_present(temp_canon: Path) -> None:
    merge_belief(temp_canon, overwrite=False)
    data = yaml.safe_load(temp_canon.read_text(encoding="utf-8"))
    assert "pair_definitions" in data
    pd = data["pair_definitions"]
    for pair_id in ("PAIR_A", "PAIR_B", "PAIR_C"):
        assert pair_id in pd, f"{pair_id} missing in pair_definitions"
        assert "members" in pd[pair_id]
        assert "theme" in pd[pair_id]
        assert "weight" in pd[pair_id]
    # 가중치 검증 (PR-07 edt_pressure 공식 일치)
    assert pd["PAIR_A"]["weight"] == 1.0
    assert pd["PAIR_B"]["weight"] == 0.5
    assert pd["PAIR_C"]["weight"] == 0.3


# ── Mirror 매핑 양방향 일관성 ──────────────────────────────────────────────────

def test_mirror_villain_hero_bidirectional() -> None:
    """HERO_BELIEFS.mirror_villain ↔ VILLAIN_BELIEFS.mirror_hero 양방향 일관성."""
    for hero_id, hbelief in HERO_BELIEFS.items():
        target_villain = hbelief.get("mirror_villain")
        if not target_villain:
            continue
        assert target_villain in VILLAIN_BELIEFS, (
            f"{hero_id} → {target_villain} 빌런이 VILLAIN_BELIEFS에 없음"
        )
        reverse = VILLAIN_BELIEFS[target_villain].get("mirror_hero")
        assert reverse == hero_id, (
            f"양방향 불일치: {hero_id} → {target_villain} → {reverse}"
        )


# ── PAIR_DEFINITIONS 자체 검증 ────────────────────────────────────────────────

def test_pair_definitions_members_match_hero_beliefs() -> None:
    """PAIR_DEFINITIONS.members와 HERO_BELIEFS.pair가 일관됨."""
    members_map: dict[str, list[str]] = {"PAIR_A": [], "PAIR_B": [], "PAIR_C": []}
    for cid, b in HERO_BELIEFS.items():
        pair = b.get("pair")
        if pair in members_map:
            members_map[pair].append(cid)
    # 각 페어 정의에 등록된 히어로가 모두 포함되어야 함
    for pair_id, members_in_def in [
        ("PAIR_A", PAIR_DEFINITIONS["PAIR_A"]["members"]),
        ("PAIR_B", PAIR_DEFINITIONS["PAIR_B"]["members"]),
        ("PAIR_C", PAIR_DEFINITIONS["PAIR_C"]["members"]),
    ]:
        for cid in members_map[pair_id]:
            assert cid in members_in_def, (
                f"{cid}가 {pair_id} members에 누락됨"
            )
