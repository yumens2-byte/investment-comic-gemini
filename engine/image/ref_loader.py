"""
engine/image/ref_loader.py
캐릭터 REF 이미지 로더 + SHA256 Canon Lock 검증.

RULE 07: 모든 캐릭터 등장 패널은 REF 이미지 멀티 입력 필수.
SHA256 불일치 시 CanonLockViolation 발생 → 파이프라인 중단.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from engine.common.exceptions import CanonLockViolation, UnknownCharacterError

logger = logging.getLogger(__name__)

_CANON_PATH = Path("config/characters.yaml")


@lru_cache(maxsize=1)
def _load_canon() -> dict[str, Any]:
    """characters.yaml을 로드 (한 번만, 이후 캐시)."""
    if not _CANON_PATH.exists():
        raise FileNotFoundError(f"characters.yaml 없음: {_CANON_PATH}")
    with open(_CANON_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _sha256(path: Path) -> str:
    """파일 SHA256 계산."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _get_char_entry(char_id: str) -> tuple[str, dict]:
    """
    char_id로 캐릭터 항목 반환.

    Returns:
        (group, entry) — group: "heroes" | "villains"

    Raises:
        UnknownCharacterError: char_id가 Canon에 없을 때.
    """
    canon = _load_canon()
    for group in ("heroes", "villains"):
        if char_id in canon.get(group, {}):
            return group, canon[group][char_id]
    raise UnknownCharacterError(char_id)


def get_ref_path(char_id: str, form: str | None = None) -> Path:
    """
    char_id의 REF 이미지 경로 반환.

    Args:
        char_id: 캐릭터 ID (예: CHAR_HERO_003).
        form: 폼 이름 (예: 'form1'). None이면 default_form 사용.

    Returns:
        REF 이미지 경로 (Path).

    Raises:
        UnknownCharacterError: char_id 없을 때.
    """
    _, entry = _get_char_entry(char_id)

    if "forms" in entry:
        target_form = form or entry.get("default_form", "form1")
        form_entry = entry["forms"].get(target_form)
        if not form_entry:
            # fallback: form1
            form_entry = entry["forms"].get("form1")
        if form_entry:
            return Path(form_entry["ref"])

    if "ref" in entry:
        return Path(entry["ref"])

    raise UnknownCharacterError(f"{char_id}: ref 경로 없음")


def verify_canon(char_id: str, form: str | None = None) -> None:
    """
    캐릭터 REF 이미지의 SHA256이 characters.yaml 기록값과 일치하는지 검증.

    SHA256이 '__TBD__' 또는 '__PENDING__'이면 검증 생략 (Phase 0 허용).

    Raises:
        CanonLockViolation: SHA256 불일치 시.
        FileNotFoundError: REF 이미지 파일이 없을 때.
    """
    _, entry = _get_char_entry(char_id)

    # 검증할 (ref_path, expected_sha256) 목록 수집
    check_list: list[tuple[Path, str]] = []

    if "forms" in entry:
        target_form = form or entry.get("default_form", "form1")
        form_entry = entry["forms"].get(target_form) or entry["forms"].get("form1")
        if form_entry:
            check_list.append((Path(form_entry["ref"]), form_entry.get("sha256", "__TBD__")))
    elif "ref" in entry:
        check_list.append((Path(entry["ref"]), entry.get("sha256", "__TBD__")))

    for ref_path, expected_sha256 in check_list:
        # __TBD__ / __PENDING__ 는 이미지 미이식 상태 → 검증 생략
        if expected_sha256 in ("__TBD__", "__PENDING__"):
            logger.debug("[ref_loader] %s SHA256 검증 생략 (TBD)", char_id)
            continue

        if not ref_path.exists():
            raise FileNotFoundError(f"REF 이미지 없음: {ref_path}")

        actual = _sha256(ref_path)
        if actual != expected_sha256:
            raise CanonLockViolation(char_id, expected_sha256, actual)

    logger.debug("[ref_loader] %s Canon 검증 통과", char_id)


def get_refs_for_panel(char_ids: list[str]) -> list[Path]:
    """
    패널에 등장하는 캐릭터들의 REF 이미지 경로 목록 반환.
    Canon 검증 포함.

    Args:
        char_ids: 패널 등장 캐릭터 ID 목록.

    Returns:
        존재하는 REF 이미지 Path 목록 (파일 없는 항목 제외).
    """
    refs: list[Path] = []
    for char_id in char_ids:
        try:
            verify_canon(char_id)
            path = get_ref_path(char_id)
            if path.exists():
                refs.append(path)
            else:
                logger.warning("[ref_loader] REF 이미지 파일 없음: %s → %s", char_id, path)
        except (UnknownCharacterError, CanonLockViolation) as exc:
            raise  # 치명적 에러 — 상위로 전파
        except Exception as exc:
            logger.warning("[ref_loader] %s REF 로드 실패 (스킵): %s", char_id, exc)

    return refs


def get_canon_name(char_id: str) -> str:
    """char_id의 영문 Canon 이름 반환."""
    _, entry = _get_char_entry(char_id)
    return entry.get("name_en", char_id)


def invalidate_cache() -> None:
    """테스트용: lru_cache 초기화."""
    _load_canon.cache_clear()
