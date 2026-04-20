# ICG Paid Telegram Manual Video Prompt Template (8s x 3 cuts)

> 사용 목적: 유료 텔레그램 채널용 수동 생성 검증(자동화 전)
> 출력 목표: 총 24초(8초 × 3컷), 9:16

## [INPUT BLOCK] 수동 입력
- DATE: {{ date }}
- SCENARIO: {{ scenario_type }}
- RISK_LEVEL: {{ risk_level }}
- EVENT_TYPE: {{ event_type }}
- HERO_ID/NAME: {{ hero_id }} / {{ hero_name }}
- VILLAIN_ID/NAME: {{ villain_id }} / {{ villain_name }}
- MARKET_FACT_1: {{ market_fact_1 }}
- MARKET_FACT_2: {{ market_fact_2 }}
- MARKET_FACT_3: {{ market_fact_3 }}

---

## [GLOBAL DIRECTION]
Create a **24-second vertical trailer** in 3 cuts (8 seconds each).
Narrative arc must be:
1) Anchor/Context briefing
2) Threat escalation
3) Hero vs Villain confrontation teaser

Style:
- cinematic news-thriller
- high contrast blue/red emergency color system
- no copyrighted design references

---

## [CHARACTER LOCK — 반드시 유지]
HERO:
- adult Korean male, late 30s
- athletic/muscular build
- blue/gold armor with white hooded cape
- cyan-blue visor and cyan energy weapon
- keep same identity across all cuts

VILLAIN:
- tall humanoid in matte black hooded cloak
- face hidden, only red glowing eyes visible
- long dark scythe
- red digital glitch particles
- keep same identity across all cuts

ANCHOR (Cut 1):
- Korean female, late 20s
- straight black hair
- business suit, professional newsroom look

---

## [CUT 1 — 0~8s | Anchor Briefing]
Prompt:
- Breaking news hard-open at 0~1s with red pulse + bass hit
- Anchor presents market crisis summary using MARKET_FACT_1~3
- Show abstract financial warning graphics (no readable text)
- End-frame hint: anchor looking right with concern, red hologram behind

Korean subtitle intent:
- "긴급 속보: 시장 이상 징후 감지"

---

## [CUT 2 — 8~16s | Threat Escalation]
Prompt:
- Villain presence emerges from digital blackout wave
- City-scale disruption visualized in abstract way
- Hero arrival at 6~8s with blue lightning counter-force
- End-frame hint: hero full silhouette on rooftop

Korean subtitle intent:
- "위협 등급 상승, 대응자 출현"

---

## [CUT 3 — 16~24s | Confrontation Teaser]
Prompt:
- Rapid intercut: villain eyes vs hero visor
- Split-frame confrontation at center
- 7.2~8s end with clean emblem card (NO TEXT)

Korean subtitle intent:
- "충돌 임박, 다음 본편 예고"

---

## [NEGATIVE BLOCK — 각 컷 끝에 동일 삽입]
ABSOLUTELY NO readable text, letters, brand logos, company names,
real people faces, celebrities, politicians, copyrighted characters,
Marvel, DC, Disney, Pixar, anime style, explicit violence, gore, blood,
nudity, minors, or any identity change of hero/villain.

---

## [OUTPUT FORMAT 가이드]
수동 생성 시 다음 항목을 기록:
- run_id: manual-{{ date }}-{{ run_no }}
- cut1_result: pass/fail + notes
- cut2_result: pass/fail + notes
- cut3_result: pass/fail + notes
- final_publish_decision: go / re-generate
