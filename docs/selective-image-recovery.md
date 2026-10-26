# 성공 이미지 보존형 콘텐츠 복구

부분 성공 회차는 공통 `image_recovery.yml`과 기존 v3 원장/RPC를 사용한다.
새 날짜별 Python·YAML은 추가하지 않는다. 날짜별 요청과 검토 장면은 JSON 데이터다.

## 계약

- 요청에 `preserve_successful_images: true`를 명시한다.
- 장면 파일은 `{"version":"selective-image-scenes-1","panels":{...}}` 형태이며,
  성공하지 않은 유료 이미지 패널만 포함한다. 성공 패널을 수정 대상으로 넣으면 중단한다.
- 성공 패널은 원장 token에 연결된 비공개 최초 입력 진단에서 프롬프트를 가져온다.
  실제 캐스트 REF 바이트, fingerprint, 원본 PNG SHA256을 모두 검증한다.
- 성공 패널의 action/setting/캐스트/프롬프트를 바꾸지 않는다. 후보에 `reuse_only`를
  넣고 패널 전문의 해시, 입력 fingerprint, 출력 hash를 묶는다.
- 이미지 단계는 모든 보호 이미지를 먼저 확인한다. 영수증이나 PNG가 없으면
  예약/provider 호출 전에 중단한다. `reuse_only`는 새 이미지 생성으로 전환되지 않는다.
- 기존 비용·거절 기록·호출 한도와 source CAS를 그대로 유지한다. SQL 스키마 변경은 없다.
- 검토 장면은 노출된 문구를 숨기는 치환이 아니라 비접촉 장면 자체의 변경이다.
  기존 모든 장면을 정지 자세로 바꾸는 자동 규칙은 추가하지 않는다.

## 공통 실행

기존 Reviewed Image Recovery에서 inspect → prepare → execute를 사용한다.
prepare는 읽기 전용이며 `reuse_only_panels`와 `generation_panels`를 보고한다.
execute는 검토한 request/candidate 해시로 CAS 등록한 뒤 기존 `stage=image`를 실행한다.
조립과 발행은 수행하지 않으며 수동 Resume 표식을 유지한다.

기존 등록을 별도로 완료한 회차만 Run Market `stage=image`로 시작/재개할 수 있다.
미등록 콘텐츠 거절 상태에서 revision 숫자만 올리거나 `stage=all/recovery`로 재실행하지 않는다.

## 2026-10-26 회차

원본 실행: `40224937364`, 원본 revision=1, 수정 revision=2.

- 보존: P1, P2, P3, P4, P6.
- 새 생성: P5만. 인물 사이 거리를 확보하고 빈 공간의 균형 잡힌 추상 에너지 경계를 표현한다.
  근접 접촉점, 떨리는 팔, 공통 스타일의 접촉 강제 지시를 수정 입력에 포함하지 않는다.
- 대사·시장 정보·캐스트·카드·state candidate는 유지한다.
- 요청: `config/image-recovery/requests/2026-10-26.json`.
- 장면: `config/image-recovery/scenes/2026-10-26.json`.

후보 등록 전에는 Reviewed Image Recovery에서 위 요청으로 prepare를 실행하고,
출력된 최신 두 SHA를 execute에 전달한다. execute는 이미지 단계도 실행하므로
성공 후 Run Market을 중복 실행할 필요는 없다.

별도 등록 후 직접 Run Market을 실행하는 경우:

| 입력 | 값 |
|---|---|
| Branch | main |
| target_date | 2026-10-26 |
| stage | image |
| generation_revision | 2 |
| source_artifact_run_id | 40224937364 |
| image_retry_v2 | false |
| dry_run | false |
| force | false |
| 나머지 기능 플래그 | auto |

성공 조건: 총 이미지 6장, 신규 provider 호출은 P5만, 보존 5장의 SHA256 불변,
asset.status=image_generated. 수동 시각 검수 후 기존 Resume/발행 절차를 따른다.
이미지 도중 실패하면 최신 부분 산출물과 원장을 먼저 확인한다. 신규 P5 PNG가 존재하는
실행을 재개할 때는 그 최신 산출물 run ID를 사용하고 원본 5장만 있는 실행으로 돌아가지 않는다.

## 검증 범위

실제 원본 artifact의 PNG 5장과 운영 원장/최초 입력 진단을 대조한 읽기 전용 파일럿에서
보존 5장, 생성 대상 P5 한 장을 검증한다. 가짜 provider를 사용하는 어댑터 통합 검증은
호출 1회와 원본 바이트 보존을 확인한다. 이는 실제 Gemini 수락이나 신규 P5 시각 품질을
증명하지 않는다. 실제 수락은 첫 운영 이미지 실행에서 별도로 확인한다.
