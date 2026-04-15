"""
scripts/generate_ref_images.py
Gemini API로 캐릭터 REF 이미지 정식 생성.

사용법:
  python -m scripts.generate_ref_images             # 전체 11종
  python -m scripts.generate_ref_images --chars CHAR_HERO_001,CHAR_VILLAIN_002
  python -m scripts.generate_ref_images --dry-run   # 프롬프트만 출력

출력:
  assets/characters/{파일명}.png  + config/characters.yaml SHA256 자동 갱신

참고:
  - 플레이스홀더 이미지가 이미 있으면 --force 없이는 덮어쓰지 않는다.
  - 생성 후 characters.yaml SHA256 자동 업데이트.
  - Git commit은 자동으로 하지 않는다 (generate_ref_images.yml 워크플로우가 담당).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import time
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("icg.gen_ref")

CANON_PATH = Path("config/characters.yaml")
ASSETS_DIR = Path("assets/characters")

# 캐릭터별 상세 이미지 프롬프트
_CHAR_PROMPTS: dict[str, str] = {
    "CHAR_HERO_001": """
Create a full-body character reference sheet for a Korean manhwa superhero named EDT (Endurance D Tiger).
CHARACTER: Male warrior in his 30s. Athletic build. Wearing sleek ETF-themed battle armor in deep blue and gold.
Helmet with tiger-eye visor. Cape made of glowing stock chart lines. Wields a chainsaw radiating ETF energy.
Expression: Determined, heroic. Eyes glowing blue.
POSE: Standing hero pose, facing RIGHT. Three-quarter view.
BACKGROUND: Deep navy blue gradient. Clean reference sheet style.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. No background clutter.
""",
    "CHAR_HERO_002": """
Full-body character reference sheet for Korean manhwa heroine Iron Securities Nuna.
CHARACTER: Tall, confident woman in her late 20s. Steel-grey armored bodysuit with data analysis interfaces.
Holographic screens floating around her wrists. Short dark hair. Professional yet battle-ready look.
Expression: Analytical, calm. Sharp eyes.
POSE: Standing with arms crossed, facing RIGHT. Three-quarter view.
BACKGROUND: Steel blue gradient. Clean reference sheet style.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast.
""",
    "CHAR_HERO_003": """
Full-body character reference sheet for Korean manhwa hero Leverage Muscle Man.
CHARACTER: Massively muscular man in his 30s. Wearing fire-orange workout gear with leverage symbols.
Carries an enormous glowing barbell crackling with financial energy. Sleeveless, showing huge arms.
Expression: Intense, battle-ready. Fiery eyes.
POSE: Raising barbell overhead, facing RIGHT. Dynamic action pose.
BACKGROUND: Deep orange-black gradient.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast.
""",
    "CHAR_HERO_004": """
Full-body character reference sheet for Korean manhwa heroine Exposure Futures Girl.
CHARACTER: Young woman in purple tech suit with futures market radar interface on her chest.
Glowing purple energy trails from her hands. Short practical hairstyle. Futuristic look.
Expression: Alert, ready. Purple glowing eyes.
POSE: Scanning stance, facing RIGHT. One hand raised with glowing energy.
BACKGROUND: Deep purple gradient.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast.
""",
    "CHAR_HERO_005": """
Full-body character reference sheet for Korean manhwa hero Gold Bond Muscle.
CHARACTER: Stocky powerful man wearing gold-and-white armored shield suit. Holds a massive circular shield
with gold and bond symbols. Grey-streaked hair, mature look. Defensive champion stance.
Expression: Steadfast, protective. Golden eyes.
POSE: Shield raised in defense, facing RIGHT.
BACKGROUND: Gold-black gradient.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast.
""",
    "CHAR_VILLAIN_001": """
Full-body character reference sheet for Korean manhwa villain Debt Titan.
CHARACTER: Enormous dark-red armored giant. Body covered in debt contract chains. Glowing red eyes.
Imposing, oppressive presence. Wears crown made of crumbling financial bonds.
Expression: Malevolent, overwhelming. Dark energy radiating.
POSE: Standing menacingly, facing LEFT. Three-quarter view.
BACKGROUND: Dark crimson gradient. Menacing atmosphere.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. Villain aesthetic.
""",
    "CHAR_VILLAIN_002": """
Full-body character reference sheet for Korean manhwa villain Oil Shock Titan.
CHARACTER: Massive oil-black armored titan. Body dripping with crude oil energy. Flames erupting from
shoulders. Oil derrick-like horns on helmet. Eyes like burning oil wells.
Expression: Destructive, overwhelming.
POSE: Charging forward menacingly, facing LEFT.
BACKGROUND: Black and fire-orange gradient.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. Villain aesthetic.
""",
    "CHAR_VILLAIN_003": """
Full-body character reference sheet for Korean manhwa villain Liquidity Leviathan.
CHARACTER: Massive sea-serpent-like humanoid villain. Teal-black liquid armor flowing like waves.
Multiple serpentine arms. Eyes glowing teal. Representing market liquidity crisis.
Expression: Predatory, calculating.
POSE: Towering intimidating stance, facing LEFT. Multiple arms spread wide.
BACKGROUND: Deep dark teal gradient. Ocean depths atmosphere.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. Villain aesthetic.
""",
    "CHAR_VILLAIN_004": """
Full-body character reference sheet for Korean manhwa villain Volatility Hydra.
CHARACTER: Multi-headed purple dragon/hydra in humanoid form. Each head represents different market fears.
Purple lightning crackling around body. VIX meter visible on chest armor.
Expression: Chaotic, unpredictable. Multiple snarling heads.
POSE: Multiple heads raised, arms spread, facing LEFT. Chaotic energy.
BACKGROUND: Deep purple-black gradient. Lightning flashes.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. Villain aesthetic.
""",
    "CHAR_VILLAIN_005": """
Full-body character reference sheet for Korean manhwa villain Algorithm Reaper.
CHARACTER: Skeletal cyber-villain in black and neon green. Half flesh, half circuit board.
Holds a scythe made of trading algorithms and dark data streams. Hollow glowing green eyes.
Expression: Merciless, algorithmic. Cold precision.
POSE: Scythe raised, facing LEFT. Menacing reaper stance.
BACKGROUND: Black and neon green gradient. Matrix-like atmosphere.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. Villain aesthetic.
""",
    "CHAR_VILLAIN_006": """
Full-body character reference sheet for Korean manhwa villain War Dominion.
CHARACTER: Massive armored warlord in blood-red and black. War-themed battle armor with geopolitical
conflict symbols. Wielding two massive swords crossed. Battle-scarred, imposing.
Expression: Wrathful, dominant. Blood-red glowing eyes.
POSE: Swords crossed, battle stance, facing LEFT.
BACKGROUND: Blood red and black gradient. War atmosphere.
STYLE: Korean manhwa / webtoon. Bold ink lines. Cel shading. High contrast. Villain aesthetic.
""",
}

_CHAR_TO_FILE: dict[str, str] = {
    "CHAR_HERO_001": "hero_edt_form1",
    "CHAR_HERO_002": "hero_iron_securities_nuna",
    "CHAR_HERO_003": "hero_leverage_muscle_man",
    "CHAR_HERO_004": "hero_futures_girl",
    "CHAR_HERO_005": "hero_gold_bond_muscle",
    "CHAR_VILLAIN_001": "villain_debt_titan",
    "CHAR_VILLAIN_002": "villain_oil_shock_titan",
    "CHAR_VILLAIN_003": "villain_liquidity_leviathan",
    "CHAR_VILLAIN_004": "villain_volatility_hydra",
    "CHAR_VILLAIN_005": "villain_algorithm_reaper",
    "CHAR_VILLAIN_006": "villain_war_dominion",
}

_NEGATIVE = """
STRICT NEGATIVE: No real people, no celebrity faces. No text overlay in image.
No copyrighted characters. No nudity. No stock logos. No photorealism.
No watermarks. Comic/manhwa art style ONLY.
"""


def _generate_one(char_id: str, output_path: Path) -> bytes:
    """Gemini API로 단일 캐릭터 이미지 생성."""
    from google import genai

    pay_key = os.environ.get("GEMINI_API_SUB_PAY_KEY", "")
    if not pay_key:
        raise RuntimeError("GEMINI_API_SUB_PAY_KEY 환경변수 없음")

    client = genai.Client(api_key=pay_key)
    prompt = _CHAR_PROMPTS[char_id].strip() + "\n\n" + _NEGATIVE.strip()

    resp = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=[prompt],
    )

    for part in resp.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            return part.inline_data.data

    raise RuntimeError(f"Gemini 응답에 이미지 없음: {char_id}")


def _update_sha256(char_id: str, file_path: Path) -> str:
    """characters.yaml SHA256 업데이트."""
    sha = hashlib.sha256(file_path.read_bytes()).hexdigest()

    with open(CANON_PATH) as f:
        canon = yaml.safe_load(f)

    if char_id in canon.get("heroes", {}):
        char = canon["heroes"][char_id]
        form = char.get("default_form", "form1")
        if "forms" in char and form in char["forms"]:
            canon["heroes"][char_id]["forms"][form]["sha256"] = sha
    elif char_id in canon.get("villains", {}):
        canon["villains"][char_id]["sha256"] = sha

    with open(CANON_PATH, "w") as f:
        yaml.dump(canon, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return sha


def main() -> None:
    parser = argparse.ArgumentParser(description="캐릭터 REF 이미지 Gemini 생성")
    parser.add_argument("--chars", default="all", help="생성 대상 (all 또는 콤마구분 char_id)")
    parser.add_argument("--force", action="store_true", help="기존 이미지 덮어쓰기")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 출력")
    args = parser.parse_args()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    char_ids = (
        list(_CHAR_TO_FILE.keys())
        if args.chars == "all"
        else [c.strip() for c in args.chars.split(",")]
    )

    logger.info("생성 대상: %d종 %s", len(char_ids), char_ids)

    for char_id in char_ids:
        if char_id not in _CHAR_TO_FILE:
            logger.warning("알 수 없는 char_id: %s (스킵)", char_id)
            continue

        fname = _CHAR_TO_FILE[char_id]
        out_path = ASSETS_DIR / f"{fname}.png"

        if out_path.exists() and not args.force:
            logger.info("[%s] 이미지 이미 존재 (--force 없이 스킵): %s", char_id, fname)
            continue

        if args.dry_run:
            logger.info("[%s] DRY_RUN 프롬프트:\n%s", char_id, _CHAR_PROMPTS[char_id][:200])
            continue

        for attempt in range(1, 4):
            try:
                logger.info("[%s] Gemini 생성 중... (시도 %d/3)", char_id, attempt)
                img_bytes = _generate_one(char_id, out_path)
                out_path.write_bytes(img_bytes)
                sha = _update_sha256(char_id, out_path)
                logger.info("[%s] ✅ 생성 완료: %s (sha256=%s...)", char_id, fname, sha[:16])
                time.sleep(3)  # Gemini rate limit 대응
                break
            except Exception as exc:
                logger.warning("[%s] 시도 %d 실패: %s", char_id, attempt, exc)
                if attempt < 3:
                    time.sleep(10)
                else:
                    logger.error("[%s] ❌ 3회 실패 — 플레이스홀더 유지", char_id)

    logger.info("완료")


if __name__ == "__main__":
    main()
