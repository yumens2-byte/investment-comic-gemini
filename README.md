# 🍌 Investment Comic Gemini (ICG)

한국 시장 데이터 → Claude 서사 → Gemini 이미지 → PIL 조립 → X/Telegram 자동 발행 파이프라인.

## 문서

상세 시스템 문서, 환경변수 목록, 설계 원칙, Supabase 스키마는 Notion에서 관리합니다.

📖 **[ICG 시스템 상세 문서 (Notion)](https://www.notion.so/3439208cbdc381f29dede581caaa12f8)**

## 빠른 실행

```bash
# 전체 파이프라인
python -m scripts.run_market --stage all

# 테스트
python -m pytest tests/ -v
```

## GitHub Actions

| 워크플로우 | 역할 |
|-----------|------|
| `📊 Run Market` | 일일 파이프라인 (STEP 2~6) |
| `🔄 Resume Episode` | PIL 조립 (STEP 7) |
| `🚀 Publish SNS` | SNS 발행 (STEP 8) |
| `✅ CI` | 코드 품질 검사 |
