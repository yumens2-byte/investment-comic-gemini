"""
scripts/issue_youtube_token.py
YouTube OAuth Refresh Token 1회 발급 스크립트 (마스터 로컬 실행 전용).

목적:
  GitHub Actions 비대화식 업로드에 필요한 YOUTUBE_REFRESH_TOKEN 을
  로컬 브라우저 승인 1회로 발급한다.

사전 준비 (GCP Console):
  1. YouTube Data API v3 활성화
  2. OAuth 동의 화면 구성 (외부 + 테스트 사용자에 본인 구글 계정 추가)
  3. OAuth 클라이언트 ID 생성 — 유형: "데스크톱 앱"
     -> CLIENT_ID / CLIENT_SECRET 확보

사용법 (로컬 PC):
  pip install google-auth-oauthlib
  python scripts/issue_youtube_token.py --client-id <ID> --client-secret <SECRET>
  (또는 env YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET 설정 후 인자 생략)

  -> 브라우저가 열리고 구글 계정 승인
  -> 콘솔에 출력된 REFRESH_TOKEN 을 GitHub Secrets(YOUTUBE_REFRESH_TOKEN)에 등록

주의:
  - scope 는 upload 최소 권한만 요청한다.
  - 발급된 토큰은 절대 코드/로그/커밋에 남기지 않는다 (콘솔 1회 출력만).
  - OAuth 동의 화면이 '테스트' 상태이면 refresh token 은 7일 후 만료된다.
    장기 운영 시 동의 화면을 '프로덕션'으로 게시할 것.
"""

from __future__ import annotations

import argparse
import os
import sys

VERSION = "1.0.0"

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> int:
    print(f"[issue_youtube_token] v{VERSION} 시작")

    parser = argparse.ArgumentParser(description="YouTube OAuth refresh token 발급 (로컬 1회)")
    parser.add_argument("--client-id", default=os.environ.get("YOUTUBE_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("YOUTUBE_CLIENT_SECRET", ""))
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="로컬 콜백 서버 포트 (기본 8765)",
    )
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        print(
            "ERROR: client-id / client-secret 누락. "
            "--client-id/--client-secret 인자 또는 "
            "YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET env 를 설정하라.",
            file=sys.stderr,
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "ERROR: google-auth-oauthlib 미설치. 실행 전: pip install google-auth-oauthlib",
            file=sys.stderr,
        )
        return 1

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    # access_type=offline + prompt=consent 조합이어야 refresh_token 이 확실히 발급된다.
    creds = flow.run_local_server(
        port=args.port,
        access_type="offline",
        prompt="consent",
    )

    if not creds.refresh_token:
        print(
            "ERROR: refresh_token 미발급. 동일 클라이언트로 기존 승인 이력이 있으면 "
            "https://myaccount.google.com/permissions 에서 앱 액세스 삭제 후 재실행하라.",
            file=sys.stderr,
        )
        return 1

    print("")
    print("=" * 60)
    print("발급 성공 — 아래 값을 GitHub Secrets 에 등록하라 (1회 출력)")
    print("=" * 60)
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 60)
    print("등록 위치: investment-comic-gemini repo > Settings > Secrets > Actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
