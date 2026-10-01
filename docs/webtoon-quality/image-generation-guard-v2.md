# Image generation guard v2

Production regeneration previously reset attempts on every run, charged unknown responses as zero, and could silently mark failed panels complete. Three reviewers checked prompt, adapter, and pipeline integration; defects were fixed and reviewed again.

The adapter now reserves each paid attempt in Supabase before sending. SDK retry attempts are explicitly one, timeout is 120 seconds. Only completed, nonterminal failures with measured usage may retry. Missing usage, quota/auth/policy failures, crashes or unsettled reservations hold the entire scope. Successful output must match its receipt; missing output must be restored, never regenerated automatically. Changed prompt/model/aspect/REF identity holds the panel.

Server limits: 3 attempts per panel, 30 per scope, 60/day and 300/month globally; $0.10 reserved per call, $3/scope, $6/day, $30/month. These are local budget policies, not provider price guarantees. A measured cost above the reservation persists the actual charge and holds the scope. Calls crossing the cap are rejected before the provider request. Service role only; anon/authenticated have no table or RPC access. Reconciliation is manual and requires provider evidence; no automatic lease expiry.

Pipeline stage guards run before analysis or persistence, query exact episode identity, reject completed episodes and unresolved publish holds, and cannot be bypassed by FORCE_RUN. Partial/missing panel lists cannot produce image_generated. Weekly final motion failures are blocked; retry configuration is bounded. Weekly video calls still use the separate existing video budget path; the new durable ledger covers image calls.

Prompt fixes remove forced winners in DRAW, battle framing in NO_BATTLE, human anatomy forcing for nonhuman designs, text/number contradictions, and character instructions on abstract cards. Missing mandatory REF blocks production images. Exact cast and performance contracts are checked.

Validation: full local suite 1,209 passed plus subsequent operational-drill unit test passed (1,210 total cases); Ruff and whitespace checks passed. Supabase migration applied, service-role transaction drill passed (reservation, scope circuit, three-call cap, unknown cost), anon/authenticated RPC privileges denied. CI now installs ffmpeg so media tests execute.

Operational beta runs real DB concurrency and restart fault tests in isolated test scopes, then one abstract real image probe (at most three measured retries within ledger caps). It does not publish, edit episodes or claim comic visual quality. Synthetic scopes use run ID and attempt; the real probe identity is stable per commit and reruns do not regenerate missing successful artifacts. Operational results and visual inspection are recorded after deployment.
