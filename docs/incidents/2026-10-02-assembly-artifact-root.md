# 2026-10-02 assembly artifact root incident

Affected episode: ICG-2026-10-02-001. Generation run 36919762103, assembly run 36921242620, publish run 36921579430, source main e3e5812.

Run Market uploaded output/episodes and output/run-market-preflight.json in one artifact. Their common root became output, retaining episodes/ inside the ZIP. Resume downloaded this ZIP under output/episodes, creating output/episodes/episodes/2026-10-02/panels. DB paths expected output/episodes/2026-10-02/panels. All eight source images were reported missing; permissive assembly created eight text cards and stored assembled. Publication validated PNG decoding but did not validate image-backed assembly, so X (four tweets) and Telegram (eight slides) sent the cards and recorded published.

Fix: upload the preflight separately to keep the episode artifact root stable; restore only exact scoped legacy nested panel paths; validate all required sources and contiguous indices before writing strict production slides; reject missing/corrupt sources rather than falling back. Disclaimer slides remain allowed without art. Text preview fallbacks are explicitly tagged and rejected by both publishers. Published resume/duplicate fences remain unchanged.

Recovery: reuse the eight original PNGs and archived episode script to generate image-backed slides with a Korean CJK font, without Gemini calls, DB changes or automatic reposting. A no-secret operational artifact replay validates this same episode on the main runner and exports recovered slides. This validates transport and assembly, not market facts, canon accuracy or full visual content approval. Existing erroneous posts are not removed or replaced automatically.
