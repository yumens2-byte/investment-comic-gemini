# ICG Phase 2.3 — Hotfix: ruff lint 오류 수정

## 문제
CI 워크플로(`ruff check . --line-length=100`)에서 신규 테스트 7개 파일에 9건 오류 발생.

## 원인
- I001 (Import block 미정렬): 7개 파일 — isort 규칙 위반
- F401 (사용 안 한 import): 3건
  - `test_g03_pair_tension.py` — `os`, `PAIR_TENSION_TRIGGER_THRESHOLD`
  - `test_g05_step15b_step4b.py` — `pytest`

## 수정 내역
`ruff check --fix`로 자동 수정 (코드 로직 변화 없음, import 블록만 정리).

## 검증
| 항목 | 결과 |
|---|---|
| `ruff check engine/ scripts/ tests/ --line-length=100 --select E,F,W,I --ignore E501` | All checks passed |
| `pytest tests/` (Flag 전체 OFF) | 443/443 PASS |
| `pytest tests/` (Flag 5종 전체 ON) | 443/443 PASS |

## 적용 방법
```bash
cd /path/to/investment-comic-gemini
unzip -o icg_phase23_hotfix.zip
git status   # tests/ 7개 파일만 변경 확인
git add tests/
git commit -m "fix(lint): ruff I001/F401 — Phase 2.3 신규 테스트 import 정리"
git push
```

## 참고
- 본 핫픽스는 테스트 파일에만 영향 (엔진/스크립트/마이그레이션/템플릿 변경 없음)
- 기존 ICG 코드베이스도 동일 ruff 설정에서 통과 확인 완료
