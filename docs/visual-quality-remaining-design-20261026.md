# 시각 품질 잔여 기능 상세설계 및 구현 계약 v1.2

- 기준: `24592ef` + 1차 개발 `95f698d`
- 일자: 2026-10-26 KST
- 적용 대상: 신규 정책 회차. 이미 성공한 PNG와 발행 완료 회차는 보존한다.
- 기본 설정: `ICG_VISUAL_QUALITY_MODE=off`. 이번 개발은 운영 설정을 바꾸지 않는다.
- 범위: R01~R08 연결 보완, 기존 R09 유지, 선언 명세와 실제 이미지 검수를 분리한다.

## 1. 계약 및 구현 위치

| 영역 | 구현 | 보장 |
|---|---|---|
| 구조화 초안 | `SceneDraft`, `normalize_drafts` | LLM은 동작·구도를 작성하고 프로그램이 해시를 계산. 승인/해시 필드를 LLM 입력으로 받지 않음 |
| 최초 입력 | `visual_quality_freeze_inputs` | revision 1의 exact source CAS, 최초 호출 전 확정, 동일 입력 멱등 |
| 정책 권위 | episode의 `visual_policy_json`, `visual_policy_sha256` | script mirror만 지워 검수 대상에서 빠질 수 없음 |
| 등록 실패 | `_visual_policy_intent`, 생성/episode trigger | 실패한 등록을 레거시 회차로 자동 취급하지 않음 |
| 입력 영수증 | `visual_quality_inputs` | revision별 append-only snapshot. 프롬프트·REF·동작 명세 변경 감지 |
| 부분 복구 | `visual_quality_register_recovery`, 공통 recovery service | 성공 입력/spec/PNG 유지, 실패 패널만 새 revision |
| 여러 생성 run | `base_manifest_with_origins`, quality register 보완 | 컨테이너 artifact와 생성 run/token/fingerprint를 분리 |
| 실제 선택본 | `source_manifest` | 유지한 패널은 원본 계획, 선택한 패널은 해당 후보의 실제 계획으로 결합 |
| 조립 | `prepare_assembly`, `compose_mobile` | 원본 비율 유지, 측정된 글자 배치, 잘림/축약/자동 재생성 금지 |
| 검수 | `visual_quality_record_review`, `visual_quality_revocations` | 원본/슬라이드 해시에 연결된 추가 전용 사람 검수 및 철회 |
| 발행 | `claim_visual_publication`, `visual_quality_require_snapshot` | 최신 검수·선택·조립본을 같은 트랜잭션에서 잠금 |
| 최종 전송 | X/TG `before_send` | 청크/배치 전 snapshot 재검사. 부분 전송 후 실패하면 기존 영수증 보존 |

새 migration은 CLI로 생성한 `supabase/migrations/20261026041544_visual_quality_contracts.sql`이다.
기존 outcome/recovery/quality SQL 이후 적용하는 추가 계약이다. 레거시 행을 정책 대상으로
일괄 변경하지 않는다. 저장소의 기존 `migrations/`와 `docs/sql/`은 자동 재적용하지 않는다.

## 2. 최초 생성과 입력 라우팅

1. `enforce`일 때만 기존 대본 호출에 `scene_performance` draft schema를 추가한다.
2. 기존 대본 생성 재시도 한도 안에서 draft를 검증한다. 별도의 추가 LLM 호출은 만들지 않는다.
3. draft는 필수 실제 행동·카메라·cast를 포함해야 한다. 정적인 문장을 프로그램이 임의의 동작으로 바꾸지 않는다.
4. 프로그램이 `_scene_performance_v2`를 정규화하고, transient draft 필드는 공개 대본에서 제거한다.
5. persist 시 정책 적용 의도를 저장하고 DB capability/입력 확정을 요구한다.
6. DB는 회차 1, `narrative_done`, 기존 state candidate, 호출 이력 없음, exact source를 확인한다.
7. 모든 유료 패널의 fingerprint/scene/REF를 한 번에 확정한 뒤 DB 정책 mirror를 반환한다.
8. image 단계에서 DB 영수증을 확인하고 고정 입력을 사용한다. 전역 설정을 off로 바꿔도 등록 의무는 사라지지 않는다.

과거 v1/v2 고정 입력의 revision 2 이상 계약은 유지한다. `INITIAL_GENERATION` 표시가
없는 과거 v2를 revision 1로 변경하는 것만으로 최초 생성에 들어갈 수 없다.
구형 performance compiler는 고정 입력을 덮어쓰지 않는다.

`off`/`shadow`는 enforce 정책을 등록하거나 생성 프롬프트에 새 명세를 주입하지 않는다.
이번 구현에서 shadow만 켜고 새 동작 초안을 얻기 위한 추가 모델 호출은 제공하지 않는다.

## 3. 정책 및 구버전 재개 방어

정책 digest는 DB가 발급하며 Python의 공개 `script_hash`와 혼용하지 않는다.
기존 해시 알고리즘을 소급 변경하지 않는다. 내부 정책·입력·명세는 별도의
`assembly-manifest-2`에서 결합한다.

manifest v2는 공개 대본, 정책 mirror, 원본 연출 계획, 실제 선택 연출 manifest,
모바일 배치 보고와 실제 슬라이드 hash를 결합한다. DB는 같은 JSON 계약을 비교하며
Python 직렬화와 PostgreSQL jsonb의 문자열 표현이 같다고 가정하지 않는다.
반환 manifest는 원본 dict와 별개의 복사본으로 만들어 이후 편집의 참조 공유를 방지한다.

DB episode trigger는 정책 삭제/변경, 고정 입력 변경, 구버전 조립 manifest,
등록 대기 상태에서의 발행, 신형 claim 없이 발행 hold를 얻는 시도를 거절한다.
신규 정책 회차를 이해하지 못하는 구버전 코드의 재개는 HOLD이며 레거시로 우회하지 않는다.

## 4. 생성 출처 및 v2 부분 복구

### 생성 출처

`base_manifest`는 파일이 들어 있는 현재 artifact와 각 패널의 실제 생성 출처를 구분한다.

```json
{
  "panel_idx": 1,
  "output_hash": "<PNG sha256>",
  "artifact_run_id": "<current container run>",
  "artifact_name": "episode-<current container run>",
  "artifact_path": "YYYY-MM-DD/panels/P1.png",
  "origin_run_id": "<original generation run>",
  "origin_token": "<immutable call token>",
  "origin_fingerprint": "<exact input fingerprint>"
}
```

서버는 현재 episode artifact pointer, 실제 success call, diagnostics의 생성 run,
해당 token/fingerprint/hash를 함께 검사한다. 생성 출처가 없거나 여러 성공 이력이
구분되지 않으면 임의로 최신 값을 선택하지 않고 HOLD한다.

### v2 복구 요청

기존 공통 recovery workflow/service를 사용한다. 회차별 Python/YAML은 추가하지 않는다.
v2 scenes 데이터는 `selective-image-scenes-2`이며 실패 패널의 `action`, `setting`,
전체 `performance` 명세를 담는다. 성공 패널은 이 문서에 넣지 않는다.

- `preserve_successful_images=true`가 필수다.
- 성공 패널의 action/setting/cast/form/spec/프롬프트/REF/hash/fingerprint를 유지한다.
- `reuse_only`와 `_preserved_performance_inputs`로 보호한다.
- 누락·변조·영수증 불일치는 재생성 대신 HOLD다.
- 거절 패널의 필수 서사 사실과 공개 내러티브는 바꾸지 않는다.
- 새 revision 등록과 terminal acknowledgement를 같은 트랜잭션에 묶는다.
- 예산·호출 수·성공 원장·과금 이력을 초기화하지 않는다.

공통 서비스의 기존 제한인 **정산된 단일 콘텐츠 terminal, 불명확한 비용/진행 중 호출 없음**을
유지한다. 여러 terminal 또는 여러 성공 이력이 섞여 출처를 확정하지 못하는 회차는
자동 확대 처리하지 않고 대사 대상으로 남긴다. 이 제한을 지원 완료로 과장하지 않는다.

quality retake는 별도 candidate 승인/예약 계약을 사용한다. 최초 생성 registry에 억지로
넣지 않고, 정확히 등록·승인한 candidate script만 자체 권한으로 검증한다.

## 5. 렌더 입력 역할과 캐논

기존 캐논/스타일 원문은 수정하지 않는다. 새 v2 프롬프트를 만들 때만 투영한다.

- Role/position, Signature Action, Entrance Cue, Panel Rules, Market Metaphor는 장면 명세가 소유한다.
- 표면 문자 강제 Identifier와 알려진 공통 접촉 staging은 투영에서 제외한다.
- 제외 이유와 원문 줄 해시, 원본/투영 해시를 고정 입력에 기록한다.
- 알 수 없거나 섞여 있는 지시는 임의로 삭제하지 않고 최종 renderer에서 검사한다.
- 신체·손 점유·소품은 원래 캐논과 form별 REF를 유지한다.
- 감사 메모는 렌더 지시가 아니며 해시와 감사 대상으로만 남긴다.

이는 자연어의 모든 모순을 해결하는 기능이 아니다. 모순을 해소할 수 없는 STYLE/CANON은
유료 호출 전에 HOLD하며, 제공자가 받아들일 확률이나 실제 품질 향상률을 보장하지 않는다.

## 6. 모바일 조립 및 실제 검수

캔버스는 1080×1350이며 원본 전체를 동일 비율로 contain한다. 원본을 상단 1050px에
다시 축소하지 않는다. 하단 300px는 불투명 자막 예약 영역이다.

| 항목 | 규격/검사 |
|---|---|
| 핵심 대사 | 44~40px, 최대 2줄 |
| 내레이션 | 36~32px, 최대 3줄 |
| 시장정보 | 28~26px, 최대 1줄 |
| 배치 | 실제 glyph 폭·높이를 측정하여 영역 안에 배치 |
| overflow | 문구 편집 대기. 문장 잘림·최소 크기 미만 축소 금지 |
| 원본 여백 | 실제 contain bbox와 좌우/상하 여백을 별도 측정 |
| 모바일 비교 | 360px/430px 폭 미리보기 |
| 실제 품질 초기값 | 이미지/모바일 모두 UNKNOWN |

잘못된 비율이나 품질 REVIEW가 성공 이미지를 자동 재생성하지 않는다.
동작/리듬/캐논/서사/문자/모바일 각각에 실제 관찰 근거가 있어야 사람이 PASS를 기록한다.
입력 점수, fake PNG, HTTP 200으로 실제 이미지 PASS를 만들지 않는다.

## 7. 검수와 발행 동시성

발행 RPC는 기존 quality RPC와 같은 advisory lock을 사용하고 episode row를 잠근다.
같은 트랜잭션에서 row version, 최신 검수, 철회 여부, 선택 version, manifest를 확인하고
기존 형식 `PUBLISH_HOLD:<uuid>` token을 만든다.

활성 hold 동안 선택/rollback/새 검수/철회/대본 변경은 거절한다. hold를 시간 만료로
자동 해제하지 않는다. 모호한 외부 전송은 기존 영수증으로 대사한 뒤 처리한다.

X는 미디어 업로드와 실제 청크 전송 직전에, TG는 배치 전송 직전에 snapshot을 재확인한다.
중간에 유효성을 잃으면 이후 전송을 중단하고 앞선 ID/영수증은 유지한다.
SNS와 DB를 하나의 원자 트랜잭션으로 취급하지 않는다.

이번 정책 v1은 이미지/슬라이드 경로용이다. video-only는 별도 검수 계약이 없어 거절하며,
정책 회차의 선택적 전투 영상은 이미지 검수로 승인한 것처럼 자동 발행하지 않는다.

## 8. 운영용 공통 진입점

검수 template 생성은 읽기 전용이며 모든 판정이 UNKNOWN이다.

```bash
python -m scripts.visual_quality --stage inspect --date YYYY-MM-DD --output <new-review.json>
python -m scripts.visual_quality --stage provenance --date YYYY-MM-DD \
  --artifact-run-id <current-run-id> --output <new-base-manifest.json>
```

실제 원본·전체 슬라이드·모바일 미리보기를 사람이 확인하고 관찰 근거를 입력한 뒤에만
review 동작을 실행한다. 아래 명령은 등록만 하며 SNS 발행을 실행하지 않는다.

```bash
python -m scripts.visual_quality --stage review --date YYYY-MM-DD \
  --review <review.json> --actor <reviewer> --confirm REVIEW_EXACT_VISUAL_ASSETS
```

철회는 `--stage revoke --review-id <id> --actor <reviewer> --note <evidence>`와 같은 confirm을
사용한다. 활성 발행 중에는 철회가 거절되므로 먼저 전송 상태를 대사한다.

## 9. 검증과 배포 조건

- Python: 신규 입력/정책/실제 선택 계획/모바일 픽셀/overflow/부분 복구/전송 중단 검사.
- 격리 SQL: 등록 CAS, 권한, 불변성, 미검수/철회/변조/구버전 거절, mixed-run, 부분 복구와 예산 보존.
- 실제 PostgreSQL 두 세션: claim/claim, claim/revoke, claim/selection 경쟁.
- 기존 CI에 두 SQL 검증 경로를 추가한다. 전용 일회성 workflow는 만들지 않는다.
- 실제 제공자 수락·시각 품질·모바일 가독성은 승인된 미발행 파일럿으로 별도 확인한다.

배포 순서는 격리 계약 및 CI 확인 → 운영 SQL 사전 점검/적용 → capability 확인 → 코드 반영 →
신규 미발행 파일럿 → 제한 활성화다. 현 개발 요청으로 운영 SQL/이미지/발행을 실행하지 않는다.
정책 등록 후에는 전역 off만으로 기존 회차의 검수 의무를 없앨 수 없다.
