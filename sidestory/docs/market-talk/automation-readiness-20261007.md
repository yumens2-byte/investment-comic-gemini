# Market Talk 자동 발행 잔여 작업 (2026-10-07 KST)

## 확인 결과

- 운영 DB 마이그레이션 적용 완료. Page `1390026310854211` 정책 등록 완료.
- inspect 실행 `37543876781`: 성공, errors=[].
- approve 실행 `37544054610`: 성공, APPROVED.
- 승인 revision: `2a4d0e2f2c0843ed7af7fa2e77f304a6e0e6f878ba6d9dd2d9050250c58cf105`.
- 해당 원고의 due_at: 2026-10-07 18:30 KST, expires_at: 같은 날 23:59 KST.
- 08시경 DB 점검: 승인 원고 1개, enabled=false, exclusive_managed=false, SENDING/UNKNOWN 0건.
- 최근 실행 로그: CHARACTER_IDS=CHAR_HERO_001, CONTROL_ENABLED=false, LIVE=false.
- SCHEDULE_ENABLED의 실제 저장값 및 Meta 게시 권한은 이번 점검으로 확인되지 않았다.

## 자동화 범위

현재 cron은 평일 18:30 KST에 유효한 APPROVED 원고 1개를 조회해 발행한다. 원고가 없으면 정상 건너뛰며 보고서를 남긴다. GitHub 예약 시작은 지연될 수 있고, 지난 슬롯 원고는 콘텐츠 검증에서 차단한다. 자동 재발행/무제한 재시도는 하지 않는다.

cron은 새 원고를 생성하거나 승인하지 않는다. 매 원고마다 근거 준비 → prepare → preview 또는 검수된 작성 → submit → inspect → 사람 approve가 필요하다. 현재 등록된 원고 하나로 다음 날에도 반복 발행되지 않는다. 새 원고 자동 생성·등록은 별도 미구현 항목이며, 도입해도 승인 단계는 사람에게 남긴다. 유료 생성 예산은 현재 0이다.

## 활성화 순서

1. 실제 Meta Page 관리/게시 권한과 최근 게시 목록 읽기 권한, 토큰 유효성, 앱 모드를 확인한다. inspect/approve 성공은 Graph API 게시 권한 검증이 아니다.
2. 해당 Page의 모든 게시 경로를 확인한다. 저장소 내 기존 외전은 같은 `FACEBOOK_CONTROL_ENABLED` 변수를 사용한다. 다른 앱/수동 동시 게시가 있으면 단일 관리 절차로 조정한다. 이 사실을 확인하기 전 exclusive_managed를 true로 기록하지 않는다.
3. 확인 후 Supabase에서 아래 SQL로 해당 Page 정책만 활성화한다. 이 문서의 SQL은 실행되지 않았다.

```sql
update icg_side.facebook_page_policy
set enabled=true, exclusive_managed=true,
    hold_reason='operator verified Page permissions and all publication paths'
where page_id='1390026310854211';
```

4. GitHub Settings → Secrets and variables → Actions → Variables에서 설정한다.

| Variable | 값 |
|---|---|
| MARKET_TALK_CHARACTER_IDS | CHAR_HERO_001 |
| FACEBOOK_CONTROL_ENABLED | true |
| MARKET_TALK_LIVE | true |
| MARKET_TALK_SCHEDULE_ENABLED | false (최초 1건 확인 전) |

5. due_at 이후, expires_at 이전에 main workflow를 수동 실행한다: stage=publish, 위 revision, confirm=YES, Evidence 비움. 실제 공개 게시이므로 승인 본문을 최종 확인한다. 당일 슬롯이 지난 경우 검증으로 차단될 수 있으므로 새 due_at의 새 revision을 생성·승인해야 한다.
6. PUBLISHED, Facebook 실제 본문/포스트 ID, DB 영수증을 대조한다. UNKNOWN/SENDING이면 재실행하지 말고 runbook의 reconcile 절차로 확인한다.
7. 최초 실제 게시 확인 후 MARKET_TALK_SCHEDULE_ENABLED=true로 변경한다. 이후 사람이 승인한 유효한 원고만 예약 발행한다.

Page 전체 상한 2건/rolling 24h, Market Talk 1건/일·최대 5건/주, 최소 간격 4시간을 유지한다. 예산 0은 게시를 막지 않으며 유료 생성만 막는다. 자동화 여부와 별개로 플랫폼의 봇 판정/차단 회피를 보장하지 않는다.

## 이번 코드 보완

- approve의 revision/YES/actor/10자 이상 Evidence 누락을 DB 호출 전에 검사하고 고정된 blocker 코드로 보고한다.
- 확인 문자열이 누락돼도 shell에서 즉시 종료하지 않고 CLI 보고서를 남긴다.
- 발행 대상이 없는 예약 실행도 SKIPPED_NO_APPROVED_CONTENT 보고서를 저장한다.
- 실행 로그에 SCHEDULE_ENABLED를 표시해 예약 설정 진단이 가능하게 한다.

## 정지

MARKET_TALK_SCHEDULE_ENABLED=false, MARKET_TALK_LIVE=false로 신규 예약/게시를 중지한다. 긴급 Page 전체 정지는 CLI pause를 사용한다. FACEBOOK_CONTROL_ENABLED=false는 기존 외전의 통합 제어도 해제하므로 긴급 정지 방법으로 사용하지 않는다.
