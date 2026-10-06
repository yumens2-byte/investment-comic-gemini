# Market Talk 개발·검증 결과

작성일: 2026-10-07 KST. 대상: investment-comic-gemini. 운영 배포/DB 적용/실제 Facebook 게시 없음.

## 검증한 기준

- 최초 분석: main `b324935bf2b5e2fe45614bc069de61c2abf69553`.
- 작업 중 추가된 `QC완화` 커밋을 확인하고 `cfc325029122fc95949aeaf817f028528c3ee49b` 기준으로 rebase했다.
- 본편 QC 완화 파일과 이번 변경 파일의 직접 충돌은 없었다.
- 원격 live API와 운영 DB를 사용하지 않은 테스트다.

## 로컬 실행 결과

| 검증 | 결과 | 의미 |
|---|---|---|
| 기존 외전 전체 + 신규 Market Talk + 본편 발행 관련 회귀 | **416 passed** | 기존 8장 발행, 경계, 신규 텍스트, UNKNOWN 복구, 본편 발행 경로 |
| 신규 검사 중 실제 Supabase/PostgREST SDK HTTP 계약 | 통과, 위 416개에 포함 | icg_side profile, RPC 인수, 읽기 전용 queue 필터 직렬화 |
| PGlite PostgreSQL 계약 | **30 passed** | migration 실행, Page/비용 제어, claim token, 원고 불변성·보류·재승인, RLS/ACL |
| Ruff 검사·포맷 | 통과 | 신규 Python 코드·테스트 |
| workflow YAML 파싱 / git diff whitespace | 통과 | 신규/변경 workflow 기본 구조 |

재현 명령:

```bash
python -m pytest sidestory/tests tests/test_publish* tests/test_run_publish* -q --disable-warnings
npm ci --ignore-scripts --prefix sidestory/tests/market_talk
npm test --prefix sidestory/tests/market_talk
ruff check sidestory/market_talk sidestory/tests/market_talk
ruff format --check sidestory/market_talk sidestory/tests/market_talk
```

기준 테스트의 한글 폰트 누락 실패는 원본 코드에서도 재현되었다. 실제 NotoSansCJK-Bold.ttc를 테스트 환경에 설치한 후 위 416개가 모두 통과했다. 테스트를 삭제하거나 한글 검증 조건을 완화하지 않았다. SDK schema()의 HTTP client 재생성 때문에 MockTransport가 유지되지 않는 구간은 테스트에서 해당 SDK transport factory를 가로채 실제 외부 연결 없이 직렬화를 확인했다. 4개 deprecation warning은 SDK timeout/verify 인수에서 발생하며 실패가 아니다.

## 추가 원격 CI

`Market Talk offline contracts`에 다음을 추가했다.

- 외부 Secret을 주입하지 않는 Python/SQL 계약 검사.
- 폐기용 PostgreSQL 16에서 독립 연결 2개가 같은 Page 발행권을 경쟁하는 검사.
- 독립 연결 2개의 비용 예약 경쟁, NULL claim 거부, UNKNOWN 차단, 본편 sentinel 불변성 검사.

실제 PostgreSQL 16 다중 연결 계약 **5개 통과**: [실행 기록](https://github.com/yumens2-byte/investment-comic-gemini/actions/runs/37490596620). 신규 Python/SQL 계약 CI와 기존 외전 PostgreSQL/PostgREST 계약도 통과했다. PGlite 검사는 별도이며 다중 연결 잠금 검증으로 표시하지 않는다.

최초 외전 CI는 기능 테스트 308개 통과 후 DR-5 경로 검사에서 실패했다. 신규 문서를 `sidestory/docs/market-talk/`, 신규 workflow를 `.github/workflows/sidestory_market_talk*.yml`로 옮겨 기존 경계 규칙을 준수하도록 수정했다. 규칙 자체는 변경하지 않았다. 최종 전체 CI 상태는 PR #99 checks에서 확인한다.

## 변경 영향

기존 파일 5개를 수정했다.

| 기존 파일 | 변경 이유 |
|---|---|
| `.github/workflows/sidestory_run.yml` | Page 공통 제어 flag 전달 |
| `sidestory/__main__.py` | flag 활성 시 기존 외전 발행기를 공통 제어로 감쌈 |
| `sidestory/adapters/facebook/graph.py` | Page 게시 이력의 제한된 페이지네이션·게시 본문 조회 |
| `sidestory/app/publish.py` | 결과 불명확+최근글 미발견 시 재게시하지 않고 보류 |
| `sidestory/tests/test_p2_publish.py` | 기존 미발견 재게시 기대값을 중복 방지 요구로 수정 |

신규 파일은 `sidestory/market_talk/`, `sidestory/tests/market_talk/`, `sidestory/supabase/`, `sidestory/docs/market-talk/`, 두 Market Talk workflow에 한정한다. 본편 `engine/`, `scripts/`, 본편 카논 및 시장 계산 소스는 변경하지 않았다. 의존성은 신규 트랙용 version/hash lock으로 추가했으며 본편 requirements 파일은 수정하지 않았다.

## 운영 전에 남는 조건

1. 실제 Meta Page/앱 게시 권한·API 버전 확인 및 텍스트 게시 계약 테스트.
2. 신규 SQL 검토·운영 적용, 기존 외전과 신규의 공통 Page 제어 활성화.
3. 인물 허용목록·생성모델/요금/예산·출처와 관측시점 등록.
4. 원고 품질 검수 실적 확보 후 감독하 실제 게시 확인.
5. 자동 출처 추출·완전 자동 원고 승인·Threads·성과 수집은 후속 단계.

이번 결과는 **검수형 예약 발행 MVP의 개발·오프라인 검증 완료**다. 모든 P0 요구의 무인 자동화나 운영 가동 완료를 뜻하지 않는다. 원고 승인과 근거 검증을 사람이 수행해야 한다.
