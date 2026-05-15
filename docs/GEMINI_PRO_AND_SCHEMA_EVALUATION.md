# Gemini Pro 업그레이드 평가 + PanelCharacter Schema 확장 평가

## 1. Gemini Pro 업그레이드 평가

### 현재 상태
- **모델**: gemini-2.5-flash-image
- **비용**: $0.00 / 패널 (무료 티어)
- **레이턴시**: 평균 9.9초 / 패널 (5.4~13.2s 범위)
- **8 패널 총 비용**: $0.00 (현재)

### 발견된 표현력 한계
1. **동적 액션 표현 약함**: panel.action 필드에 "synchronized dual attack", "coordinated counter-strike" 같은 동적 묘사가 들어가도 정적 standing pose로 렌더링 (마스터 직접 지적)
2. **REF 이미지의 baseline pose 답습**: standing pose의 REF 이미지는 동적 액션 명시에도 standing 유지
3. **세부 동작 표현**: 손가락 위치, 미세 표정, 협공 자세 등 미세 표현은 제한적

### Gemini Pro 업그레이드 시 기대 효과 (Google AI 공식 비교 기준)
- **표현력**: Pro는 Flash 대비 미세한 동작/표정 표현 우수
- **REF 이미지 해석**: Pro는 "REF는 외형 참조, 액션은 별도 지시 따름" 같은 복잡한 분기 처리 우수
- **비용**: gemini-2.5-pro-image는 유료 (예상 $0.04 / 이미지 기준 시 8패널 = $0.32/EP)
- **레이턴시**: Pro는 Flash 대비 약 1.5~2배 느림 (15~25s/패널 예상)
- **8 패널 EP당 추가 비용**: 현재 $0.00 → $0.32 (예상)

### 권고
- **단계 1**: 본 패치(prompt_builder DYNAMIC ACTION 강화 + Iron Nuna 동적 REF) 적용 후 **1주 운영 관찰**
- **단계 2**: 패치 효과 부족 시 Pro 업그레이드 진행
- **단계 3**: 변경 시 `engine/image/gemini_client.py`의 model_name만 변경 (코드 영향 최소)

### 의사결정 기준
- 패치 적용 후 동적 액션 비율 50% 미만 → Pro 검토
- 50% 이상 → Flash 유지 + 비용 절감 우선

## 2. PanelCharacter Schema `action` 필드 추가 평가

### 현재 schema (engine/narrative/schema.py)
```python
class PanelCharacter(BaseModel):
    char_id: str
    role: Literal["hero", "villain", "npc"]
    form: str | None = None
    position: Literal["LEFT", "RIGHT", "CENTER"]
```

### 제안 schema
```python
class PanelCharacter(BaseModel):
    char_id: str
    role: Literal["hero", "villain", "npc"]
    form: str | None = None
    position: Literal["LEFT", "RIGHT", "CENTER"]
    action: str | None = Field(   # 신규
        default=None,
        max_length=120,
        description="이 캐릭터의 패널 내 구체적 동작 (영문, 동사 중심)"
    )
```

### 영향 범위
| 항목 | 영향 |
|---|---|
| `engine/narrative/schema.py` | 신규 optional 필드 추가 (백워드 호환) |
| `engine/image/prompt_builder.py` | 캐릭터별 action 텍스트 프롬프트 합성 로직 추가 |
| `config/prompts/narrative_user.j2` | Claude가 각 캐릭터에 action 작성하도록 지시 추가 |
| `engine/narrative/claude_client.py` | 영향 없음 (Pydantic 자동 처리) |
| `engine/narrative/episode_type_engine.py` | 영향 없음 |
| `tests/test_schema.py` | 신규 테스트 1~2건 추가 (optional 필드 검증) |
| 기존 443 테스트 | 모두 PASS 유지 (optional이므로) |
| Claude 토큰 사용량 | output 증가 추정 +5~10% (8 패널 × 1~3 char × 50~80 char) |
| 운영 시기 | Phase 2.4 권고 (Phase 2.3 점진 ON 완료 후) |

### 권고
- **현재 패치(prompt_builder DYNAMIC ACTION 강화)로 1주 운영 관찰 우선**
- 효과 부족 시 Phase 2.4에서 schema 확장 진행
- schema 확장 후 prompt_builder에서 캐릭터별 action을 `panel.action`보다 우선 사용

### 단계별 진행안
1. **Phase 2.3 (현재)**: prompt_builder DYNAMIC ACTION + Iron Nuna 동적 REF + Notion ALLIANCE 강화
2. **Phase 2.4 (후속)**: schema에 action 추가 + Claude 프롬프트 갱신
3. **Phase 2.5 (장기)**: REF 이미지 11종 전체 동적 포즈 재생성 + Gemini Pro 검토

## 3. 종합 의사결정 매트릭스

| 액션 | 즉시 효과 | 비용 | 위험도 | 권고 시점 |
|---|---|---|---|---|
| prompt_builder DYNAMIC ACTION 강화 | 중 | 없음 | 낮음 | ✅ 본 패치 적용 |
| Iron Nuna 동적 REF | 중-고 | Gemini Pro $0.32 (1회) | 낮음 | ✅ 본 패치 적용 |
| ALLIANCE role/char_id 강화 | 고 | 없음 | 낮음 | ✅ 본 패치 적용 |
| 나머지 10종 캐릭터 동적 REF | 고 | Gemini ~$3.2 (1회) | 낮음 | Iron Nuna 검수 후 |
| Schema action 필드 | 고 | 토큰 +10% | 중 | Phase 2.4 |
| Gemini Pro 업그레이드 | 매우 고 | $0.32/EP × 30 = $10/월 | 낮음 | 1주 운영 후 |
