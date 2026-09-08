# Pipeline Watchdog 정의·장애 분석·보강

## 정의와 안전성 목적

Pipeline Watchdog은 본 파이프라인과 **독립된 감시 경로**에서 실행 결과를 관찰하고,
실패·취소·시간 초과를 운영자에게 전달하는 감시 장치다. 작업 자체의 재시도 로직과 달리
“파이프라인이 실패했다는 사실이 묻히는 것”을 막는 것이 핵심 목적이다.

이 저장소에서는 GitHub Actions의 `workflow_run(completed)` 이벤트를 사용한다. 감시 대상
워크플로가 끝나면 Watchdog이 별도 run으로 시작되고, 성공이 아닌 경우 Telegram 내부
채널에 원본 run 링크를 보낸다. 따라서 원본 workflow의 마지막 알림 step이 실행되지
못하는 취소·시간 초과도 독립적으로 통지할 수 있다.

## 정상 동작하지 않은 원인

`workflow_run.workflows`는 workflow 파일명이 아니라 최상위 `name`을 **이모지와 공백까지
완전히 동일하게** 비교한다. 기존 Watchdog의 아래 두 필터에는 실제 이름에 있는 이모지와
연속 공백이 빠져 있어 해당 이벤트가 발생해도 Watchdog이 시작되지 않았다.

- `🚀  Publish Shorts (ICG Video Track)`
- `🔄  Weekly Digest Shorts (ICG Video Track)`

또한 Telegram Secret이 없을 때 성공 코드로 끝났기 때문에, 알림 경로가 구성되지 않은
상태도 정상(green)으로 보이는 fail-open 문제가 있었다. 실제 파이프라인을 고의로 실패시키지
않고 알림을 검증할 진입점도 없었다.

## 보강 내용과 운영 방법

1. 감시 이름을 실제 workflow 이름과 정확히 맞추고, 테스트가 다섯 파일의 이름을 직접
   읽어 이후 이름 변경으로 인한 회귀를 탐지한다.
2. `workflow_dispatch` smoke test를 추가했다. Actions의 **Pipeline Watchdog → Run workflow**로
   실행하면 테스트 Telegram 메시지가 와야 한다.
3. `TELEGRAM_BOT_TOKEN` 또는 `TELEGRAM_INTERNAL_CHANNEL_ID`가 없으면 Watchdog을 실패시켜
   설정 누락이 Actions 화면에 드러나게 했다.
4. 일시적 네트워크 오류는 제한적으로 재시도하고, HTTP 200뿐 아니라 Telegram JSON의
   `ok=true`까지 확인한다.
5. 권한을 빈 집합으로 제한했다. `workflow_run`은 Secret을 사용할 수 있는 강한 이벤트이므로
   이벤트가 가리키는 브랜치의 코드를 checkout하거나 실행하지 않는다.

Repository Actions Secrets에 두 값을 등록한 뒤 smoke test를 실행한다. 알림 수신과 Watchdog
run 성공을 모두 확인해야 운영 검증이 완료된다.

## 의도적으로 남은 한계

이 방식은 **시작된 run의 비정상 종료**를 감시한다. GitHub 스케줄 자체가 누락되어 run이
전혀 생성되지 않은 경우에는 `workflow_run` 이벤트도 없으므로 탐지할 수 없다. 이 문제는
GitHub Actions 밖의 주기적 synthetic monitor 또는 마지막 성공 시각을 조회하는 별도
heartbeat 감시로 다뤄야 한다.
