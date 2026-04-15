"""
scripts/migrate_ref_images.py
EDT Notion 허브에서 캐릭터 REF 이미지를 가져와 ICG assets/characters/ 에 이식.

작동 방식:
  1. Notion API로 캐릭터 관련 페이지들의 이미지 블록 URL 수집
  2. 각 URL에서 PNG 다운로드
  3. ICG 파일명으로 저장
  4. SHA256 계산 → characters.yaml 자동 갱신

실행:
  python -m scripts.migrate_ref_images
  python -m scripts.migrate_ref_images --dry-run   # URL만 확인

필요 환경변수:
  NOTION_API_KEY — EDT investment-os Notion 통합 토큰
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import time
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("icg.migrate")

CANON_PATH = Path("config/characters.yaml")
ASSETS_DIR = Path("assets/characters")

# Notion 허브에서 이미지가 포함된 페이지 ID 목록
# 각 항목: (page_id, {추출할_이미지_키워드: ICG파일명})
NOTION_IMAGE_PAGES: list[tuple[str, dict[str, str]]] = [
    # 빌런 4종 REF 이미지 프롬프트 팩 (확인된 이미지 포함)
    (
        "32c9208cbdc381458ff6d9d02155c5df",
        {
            "Volatility_Hydra": "villain_volatility_hydra.png",
            "volatility_hydra_ref": "villain_volatility_hydra.png",
            "liquidity_leviathan_ref": "villain_liquidity_leviathan.png",
            "algorithm_reaper_ref": "villain_algorithm_reaper.png",
        },
    ),
    # 빌런 REF v2.6 패치 페이지 (Debt Titan + Oil Shock Titan)
    (
        "32c9208cbdc381b784adc15d4702c9e1",
        {
            "debt_titan": "villain_debt_titan.png",
            "oil_shock": "villain_oil_shock_titan.png",
            "war_dominion": "villain_war_dominion.png",
        },
    ),
    # Gold Bond Muscle REF 재제작
    (
        "32c9208cbdc381039de7d600099a0bec",
        {
            "gold_bond": "hero_gold_bond_muscle.png",
            "1000035796": "hero_gold_bond_muscle.png",
        },
    ),
    # 히어로 3종 REF v2.7
    (
        "32c9208cbdc38199aa5cdc17e0919819",
        {
            "1000036486": "hero_futures_girl.png",
            "futures_girl": "hero_futures_girl.png",
            "1000036008": "hero_iron_securities_nuna.png",
            "iron_nuna": "hero_iron_securities_nuna.png",
            "1000035796": "hero_gold_bond_muscle.png",
        },
    ),
    # Iron Securities Nuna 최신 캐논 확정
    (
        "3359208cbdc381979a0dcffac41175b6",
        {
            "1000037022": "hero_iron_securities_nuna.png",
        },
    ),
    # EDT ETF Form 시스템 (EDT Form images)
    (
        "3309208cbdc381b2ad43ef26809db67c",  # 08_PREIMAGE v2.8 page
        {
            "1000036072": "hero_edt_form1.png",
            "1000036724": "hero_edt_form1.png",
            "1000036726": "hero_edt_form1.png",
            "edt_etf": "hero_edt_form1.png",
        },
    ),
]

# 추가 탐색 페이지 (에피소드 패키지에서 히어로/빌런 이미지 수집)
EPISODE_PAGES: list[str] = [
    "3389208cbdc3810f9222f758e0a50d73",  # Ep01 소스 패키지
    "3389208cbdc381539ad5ec6b07e3e764",  # Ep02 소스 패키지
    "3309208cbdc381aab43ad48f95fc3b5a",  # 3회차 이미지 팩
    "3319208cbdc38124a862d7888ad9b6dd",  # 4회차 이미지 팩 (War Dominion)
    "3329208cbdc3819da91ccdb0260fdf14",  # 5회차 이미지 팩 (Futures Girl)
    "3309208cbdc381c7bd47e65b3b5604f4",  # ETF Form 이미지 검증
]

# 파일명 키워드 → ICG 파일명 글로벌 매핑 (에피소드 페이지용)
GLOBAL_KEYWORD_MAP: dict[str, str] = {
    "1000036072": "hero_edt_form1.png",
    "1000036724": "hero_edt_form1.png",
    "1000036726": "hero_edt_form1.png",
    "1000036078": "hero_leverage_muscle_man.png",
    "1000036008": "hero_iron_securities_nuna.png",
    "1000037022": "hero_iron_securities_nuna.png",
    "1000036486": "hero_futures_girl.png",
    "1000037195": "hero_futures_girl.png",
    "1000035796": "hero_gold_bond_muscle.png",
    "1000036076": "villain_oil_shock_titan.png",
    "1000036074": "villain_war_dominion.png",
    "1000036075": "villain_war_dominion.png",
    "debt_titan": "villain_debt_titan.png",
    "liquidity_leviathan": "villain_liquidity_leviathan.png",
    "Volatility_Hydra": "villain_volatility_hydra.png",
    "volatility_hydra": "villain_volatility_hydra.png",
    "algorithm_reaper": "villain_algorithm_reaper.png",
}


def _get_notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }


def _get_page_blocks(page_id: str, token: str) -> list[dict]:
    """Notion 페이지의 모든 블록 가져오기."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = _get_notion_headers(token)
    blocks: list[dict] = []
    cursor = None

    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor

        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning("블록 조회 실패 page_id=%s status=%d", page_id, resp.status_code)
            break

        data = resp.json()
        blocks.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return blocks


def _extract_image_urls(blocks: list[dict]) -> list[tuple[str, str]]:
    """
    블록 목록에서 이미지 URL과 파일명 추출.

    Returns:
        [(원본_url, 추정_파일명)] 목록
    """
    results = []
    for block in blocks:
        btype = block.get("type", "")

        # 이미지 블록
        if btype == "image":
            img_data = block.get("image", {})
            file_type = img_data.get("type", "")
            if file_type == "file":
                url = img_data.get("file", {}).get("url", "")
                # URL에서 파일명 추출
                fname = url.split("/")[-1].split("?")[0]
                if url:
                    results.append((url, fname))
            elif file_type == "external":
                url = img_data.get("external", {}).get("url", "")
                fname = url.split("/")[-1].split("?")[0]
                if url:
                    results.append((url, fname))

    return results


def _download_image(url: str, dest_path: Path) -> bool:
    """이미지 URL에서 다운로드 후 저장."""
    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        data = resp.content
        if data[:4] == b"\x89PNG" or data[:3] == b"\xff\xd8\xff":
            dest_path.write_bytes(data)
            return True
        logger.warning("PNG/JPEG가 아닌 응답: %s", url[:60])
        return False
    except Exception as exc:
        logger.warning("다운로드 실패 %s: %s", dest_path.name, exc)
        return False


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


# ICG 파일명 → 캐릭터 ID 매핑
_ICG_FILE_TO_CHAR_ID: dict[str, str] = {
    "hero_edt_form1.png": "CHAR_HERO_001",
    "hero_iron_securities_nuna.png": "CHAR_HERO_002",
    "hero_leverage_muscle_man.png": "CHAR_HERO_003",
    "hero_futures_girl.png": "CHAR_HERO_004",
    "hero_gold_bond_muscle.png": "CHAR_HERO_005",
    "villain_debt_titan.png": "CHAR_VILLAIN_001",
    "villain_oil_shock_titan.png": "CHAR_VILLAIN_002",
    "villain_liquidity_leviathan.png": "CHAR_VILLAIN_003",
    "villain_volatility_hydra.png": "CHAR_VILLAIN_004",
    "villain_algorithm_reaper.png": "CHAR_VILLAIN_005",
    "villain_war_dominion.png": "CHAR_VILLAIN_006",
}


def run(dry_run: bool = False) -> dict[str, bool]:
    """
    메인 이식 실행.

    Returns:
        {icg_파일명: 성공여부} 딕셔너리
    """
    token = os.environ.get("NOTION_API_KEY", "")
    if not token:
        raise RuntimeError("NOTION_API_KEY 환경변수 없음")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}
    downloaded: set[str] = set()

    all_pages = list(NOTION_IMAGE_PAGES)
    # 에피소드 페이지도 글로벌 키워드 맵으로 처리
    for pid in EPISODE_PAGES:
        all_pages.append((pid, GLOBAL_KEYWORD_MAP.copy()))

    for page_id, keyword_map in all_pages:
        logger.info("페이지 블록 조회: %s", page_id)
        try:
            blocks = _get_page_blocks(page_id, token)
        except Exception as exc:
            logger.warning("페이지 조회 실패 %s: %s", page_id, exc)
            continue

        image_urls = _extract_image_urls(blocks)
        logger.debug("  이미지 %d개 발견", len(image_urls))

        for url, orig_fname in image_urls:
            # 키워드 매칭으로 ICG 파일명 결정
            icg_fname = None
            for keyword, target_fname in keyword_map.items():
                if keyword.lower() in orig_fname.lower() or keyword.lower() in url.lower():
                    icg_fname = target_fname
                    break

            if not icg_fname:
                continue

            if icg_fname in downloaded:
                continue  # 이미 다운로드됨

            dest = ASSETS_DIR / icg_fname
            if dest.exists() and not dry_run:
                logger.info("  이미 있음 (스킵): %s", icg_fname)
                downloaded.add(icg_fname)
                results[icg_fname] = True
                continue

            if dry_run:
                logger.info("  [DRY_RUN] %s → %s", orig_fname[:40], icg_fname)
                continue

            logger.info("  다운로드: %s → %s", orig_fname[:40], icg_fname)
            ok = _download_image(url, dest)
            if ok:
                sha = _update_sha256(_ICG_FILE_TO_CHAR_ID.get(icg_fname, ""), dest)
                logger.info("  ✅ %s (sha256=%s...)", icg_fname, sha[:12])
                downloaded.add(icg_fname)
                results[icg_fname] = True
            else:
                results[icg_fname] = False

            time.sleep(0.5)  # Notion 레이트 리밋 대응

    # 완료 보고
    success = [k for k, v in results.items() if v]
    failed = [k for k, v in results.items() if not v]
    logger.info("완료: 성공 %d / 실패 %d", len(success), len(failed))
    if failed:
        logger.warning("실패: %s", failed)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="EDT REF 이미지 ICG 이식")
    parser.add_argument("--dry-run", action="store_true", help="URL만 확인, 다운로드 안 함")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
