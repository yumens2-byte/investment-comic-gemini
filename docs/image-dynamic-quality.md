# 이미지 동작·구도 품질 개선: 개발 및 운영 절차

대상은 Run Market의 정적인 6개 이미지와, 기존 성공본을 보존한 품질 개선 재생성이다. 이 문서는 운영반영 전 코드와 테스트 범위를 설명한다. 신규 SQL은 아직 운영에 적용하지 않는다.

## 변경된 동작

- `scene-performance-2`에서 행동·신체 지지·시선·잔동작, 샷 크기·시점·롤·초점을 각각 지정한다. 인물 간 비접촉 제약과 이동/회전/반응을 분리한다.
- 이야기 속 인물과 실제 화면에 보이는 인물을 구분한다. CU/ECU를 맞추려고 전신이나 화면 밖 인물을 추가하지 않는다. Iron Nuna의 왼팔 방패·오른손 라이플은 구조적으로 고정한다.
- 새로운 검토 입력은 `reviewed-image-inputs-2`다. 동작 명세·실제 프롬프트·참조 파일·모델·비율을 묶어 확인한다. 구버전 입력은 기존 검증을 유지한다.
- 신규 경로는 `gemini-2.5-flash-image`의 `aspect_ratio=4:5`를 SDK에 전달한다. 공식 문서의 4:5 출력은 896×1152이므로 픽셀의 정확한 4:5 일치를 가정하지 않는다. 최종 조립은 원본 비율을 유지하고 1080×1350 캔버스에 여백을 둔다.
- 미분류 CLIMAX에 자동 타격/IMPACT를 주입하지 않는다. `shield` 명사만으로 방어 동작을 분류하지 않으며 `fire crown`을 발사로 분류하지 않는다.
- 생성 성공과 품질 통과는 구분한다. 새 후보는 생성 직후 `quality_status=UNKNOWN`이다. 명세의 구도 다양성 검사도 실제 이미지 판정으로 표시하지 않는다.

## 배포 대상과 순서

1. PR의 CI 네 작업이 모두 통과했는지 확인한다. 로컬 PostgreSQL 시뮬레이션과 CI의 실제 PostgreSQL 동시성 검증을 구분한다.
2. 운영반영 승인 후 `docs/sql/image-quality-candidates.sql`을 적용한다. 선행 revision/recovery/retry/diagnostics/outcome-v3 계약이 설치되어 있어야 한다. SQL을 중복 실행하지 않는다. 이 파일은 배포 제안 SQL이며 기존 테이블/원장을 초기화하지 않는다.
3. 테이블 3개, RPC 8개, 호출 원장의 `quality_candidate_id`·`quality_run_id` 및 고유 인덱스가 생성되었는지 확인한다. RLS·서비스 역할 권한을 확인한다.
4. 이후 PR을 main에 병합한다. Resume workflow의 `ICG_IMAGE_QUALITY_CANDIDATES_ENABLED=true`는 위 DB 계약을 요구한다. 후보가 없는 일반 에피소드는 기존 조립을 계속한다.
5. 신규 경로의 읽기 점검 후 게이트 A를 진행한다. 이번 개발 테스트에 실제 유료 파일럿이나 운영 발행은 포함하지 않는다.

모든 신규 함수는 `SECURITY INVOKER`, 빈 search_path를 사용한다. 공개 역할은 신규 테이블과 RPC에 접근하지 못한다. 공개 저장소에 실제 프롬프트·참조 사본·운영 대본·승인 묶음·키를 커밋하지 않는다.

## 게이트 A: 생성할 입력 고정 및 승인

원본 DB `script_json`과 원본 이미지 아티팩트를 확보한다. 후보 대본은 원본의 내레이션·캐릭터·사건·연속성·기타 메타데이터를 보존하고 `action`, `setting`, 동작 명세만 바꾼다. 모든 유료 패널의 명세가 필요하다. 생성 대상은 그중 일부만 선택할 수 있다. 권장 파일럿은 P3·P5·P6이다.

각 명세 필드는 `engine/image/scene_performance.py`를 기준으로 한다. `config/image_performance_hands.yaml`의 소품 ID는 `shield`, `rifle`이다. 예시 계약은 `tests/test_dynamic_image_quality.py`에 있고 실제 운영 캐릭터 ID로 치환해야 한다. 기존 대본에 `_scene_contracts`가 있어도 prepare가 사본에서만 제거한다.

원본 선택 매니페스트는 모든 유료 패널에 아래 항목이 있어야 한다:

```json
[
  {
    "panel_idx": 1,
    "output_hash": "<원본 PNG의 SHA-256>",
    "artifact_run_id": "39331869960",
    "artifact_name": "episode-39331869960",
    "artifact_path": "2026-10-20/panels/P1.png"
  }
]
```

예시는 한 패널을 보여준다. 최초 등록 시 해시는 성공 원장과, 입력 진단의 실제 원본 run ID까지 맞아야 한다. 진단이 없는 과거 생성본은 자동 승인하지 않는다. 먼저 증거를 대조·조정한다. 이미 선택 버전이 있다면 현재 `image_quality_selections.manifest` 전체를 사용한다.

무과금 준비:

```bash
export ICG_GENERATION_REVISION=3
python -m scripts.image_quality prepare \
  --source /private/source.json --candidate /private/candidate-script.json \
  --manifest /private/base-manifest.json --base-run-id 39331869960 \
  --revision 3 --panels 3,5,6 --budget 0.30 --expected-version 0 \
  --output /private/quality-bundle.json
```

준비 단계는 DB를 쓰거나 이미지 API를 호출하지 않는다. 스타일/캐릭터 프롬프트는 기존 로더로 해석해 최종 입력을 고정한다. 엄밀한 오프라인 준비가 필요하면 로더 입력도 승인된 사본으로 고정해야 한다. 출력 경로는 새 파일이어야 한다. `0.30`은 세 번의 예약 상한 합계이며 실제 과금 견적 또는 제공자 요금 보장이 아니다.

등록은 운영반영 이후 서비스 환경에서 명시적으로 수행한다:

```bash
DRY_RUN=false python -m scripts.image_quality register --live \
  --bundle /private/quality-bundle.json --output /private/register-receipt.json
```

등록은 DRAFT만 만든다. 응답의 `id`와 `digest`를 기록한다. 원본 상태는 `image_generated` 또는 `assembled`여야 하며 원본 성공본·대본·아티팩트 포인터가 바뀌면 거절된다. 공개 프롬프트 변경과 등장인물 변경도 거절된다.

Actions → **Image Quality Human Gates** → `stage=approve`에 id, digest, revision, 검토 근거 note(20자 이상)를 입력한다. 생성 대상·스토리보드·완성 프롬프트·캐논·비용 한도를 사람이 먼저 확인한다. 승인 후 별도 실행으로 `stage=generate`, 동일 id/revision을 입력한다.

한 후보/패널에는 유료 호출을 한 번만 허용한다. 새 후보도 기존 scope의 패널별 최대 3회, 에피소드/일/월 횟수·비용을 계속 공유한다. 후보 자체 호출 수/예산도 검사한다. 거절·불확실 결과·유효하지 않은 PNG에 대해 자동 유료 재시도를 하지 않는다. 같은 성공본은 원래 해시의 파일이 있을 때만 재사용한다. 없으면 아티팩트 복원을 요구한다.

## 게이트 B: 실제 이미지·조립 미리보기 검수 및 선택

생성 Actions의 `image-quality-<id>` 아티팩트에 원본 PNG, `result.json`, `previews/Pn-slide.png`가 저장된다. 부분 생성 후 실패해도 확보한 PNG는 보존한다. 프롬프트가 포함된 generation.log나 private receipt는 업로드하지 않는다. 검수 시 기존 원본과 새 원본, 실제 조립 미리보기, 에피소드 전체를 비교한다.

`stage=review`에 id/digest/revision과 아래 형태의 `review_json`을 입력한다. 대상 패널 모두를 포함한다. 이 JSON은 사람이 실제 이미지를 확인한 기록이며 모델이 자동 PASS로 채우는 값이 아니다.

```json
{
  "episode_continuity": "PASS",
  "evidence": "전체 에피소드의 인과·캐릭터·구도 및 조립본을 실제 대조함",
  "panels": [
    {
      "panel_idx": 3,
      "output_hash": "<생성 결과의 정확한 SHA-256>",
      "safety": "PASS",
      "canon": "PASS",
      "quality": "PASS",
      "assembly": "PASS",
      "evidence": "자세·샷·시선·소품·텍스트 영역을 원본 및 조립본으로 확인함"
    }
  ]
}
```

샷 준수, 몸의 변화, 초점, 손·인체·소품, 무문자/캐논 표기 정책, 이야기 사실을 확인한다. 일반적인 연출 경고는 `quality=REVIEW`로 기록하고 최종 선택 근거에 수용 이유를 적을 수 있다. 안전·캐논·조립은 PASS가 필요하다. UNKNOWN 또는 잘못된 이미지 해시로 검수 완료할 수 없다.

이후 별도 `stage=select`를 실행한다. 최초 `expected_version=0`, 이후에는 현재 선택 버전을 입력한다. 선택된 후보는 SELECTED 상태가 되고, 선택은 원자적으로 매니페스트만 바꾸며 기존 이미지·원장·원본 포인터·에피소드 상태를 덮어쓰지 않는다. 선택된 패널과 유지한 패널을 합친 완성 매니페스트가 저장된다. 선택 자체는 발행 승인이 아니다.

## 선택본 조립과 발행

Resume Episode를 수동 실행하여 `episode_id`, `quality_selection_version`을 입력한다. assembled 상태의 재조립이면 `force=true`가 필요하다. 선택 매니페스트에 등록된 여러 run의 아티팩트를 내려받아, 모든 PNG의 경로·해시·유효성을 검증한 후 조립한다. 선택한 패널 외에는 원본을 그대로 사용한다.

선택 버전은 조립 매니페스트에 결합된다. 그 후 롤백/새 선택이 발생하면 기존 슬라이드는 발행 전 검증에서 거절되며 재조립해야 한다. 발행은 기존 별도 발행 절차를 사용한다. 품질 후보 workflow는 발행 함수를 호출하지 않는다.

후보가 DRAFT/APPROVED/REVIEWED 상태이거나 선택 매니페스트가 있으면 예약 Resume는 `quality_human_gate_pending`으로 건너뛴다. 발행 사전 점검과 실행에서도 미검토 후보 및 오래된 선택 버전을 차단한다. 일반 QC 경고를 시스템 오류로 바꾸는 기능이 아니라, 명시적으로 시작한 휴먼게이트를 예약 조립이 지나치지 않게 하는 처리다.

## 취소·복원 및 실패 처리

- 후보를 포기할 때 `stage=cancel`로 id/digest/revision/note를 입력한다. 사용 중이거나 unknown인 호출은 먼저 정산·조정해야 하며 취소로 지워지지 않는다.
- 이미 선택한 결과를 복원할 때 `stage=rollback`에 scope, expected_version, target_version, note를 입력한다. 최초 원본은 history의 0번이다. 복원도 새 선택 버전을 생성한다. published 상태는 거절한다.
- 선택 후 후보만 cancel해도 현재 선택은 바뀌지 않는다. 원본으로 돌아가려면 rollback을 실행하고 반환된 새 버전으로 재조립한다.
- 과거 호출·비용·진단·후보 이력은 삭제하지 않는다. 성공 이미지가 있는 재실행은 원본 아티팩트를 복원해야 한다. 후보별 아티팩트는 보존 기간 30일이므로 운영 보존 정책에 따라 만료 전에 확보한다.
- DB 계약 적용 전에는 새 workflow를 활성화하지 않는다. 코드 롤백 시에도 선택 이력은 보존한다. 선택본을 사용한 슬라이드는 이전 코드로 우회 발행하지 말고, 원본 선택 복원 후 검증된 버전으로 재조립한다.

## 검증 범위와 한계

단위·모의 통합 테스트는 명세 모순, 안전 지시, 캐논 손 점유, 고정 입력 변경, SDK 비율 전달, 단일 호출·성공 재사용, 왜곡 방지, 해시 검증, 선택 버전 변경, 예약 휴먼게이트, workflow 공개 범위를 확인한다.

PGlite는 실제 PL/pgSQL과 역할 권한·누적 예산·선택/복원 계약을 실행한다. 별도 CI PostgreSQL 16 작업은 두 세션에서 예약과 선택을 동시에 실행하여 각각 한 건만 승리하는지 확인한다. 공급자의 실제 이미지 품질·콘텐츠 허용·실제 과금은 이 테스트로 입증하지 않는다. 이는 운영반영 후 승인된 소규모 유료 파일럿의 검증 범위다.

참고한 공식 사양:

- [Google Gemini 이미지 생성 및 비율](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)
- [Supabase Database Functions 및 실행 권한](https://supabase.com/docs/guides/database/functions)
