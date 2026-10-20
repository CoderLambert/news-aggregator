# Channel recovery execution ledger
User plan: 频道核验恢复与独立管理列表重构 (2026-10-21 conversation).
Base: origin/main b03a3dfb41911b06dfb24c31074f4faf60fe8845; original checkout d8afd85 remains untouched.
Tasks: recovery persistence/worker; list and batch APIs; independent accessible UI; isolated/live/local/browser validation.
Pre-flight: recovery produces operation IDs/phase/resolution consumed by list/detail/batch; API produces viewer-scoped DTO consumed by UI.
Ruling: work from origin/main and preserve native local verification endpoint compatibility, whose implementation exists only in the local image. Cost if wrong: local candidate may contain other uncommitted behavior; compare code before local update.
Baseline: Docker Python 3.12, network none, disposable DB: test_operations + test_control_worker -> 43 passed.
Recovery/API: 9 focused tests passed, full existing RSS suite 594 passed before overview/current-instance changes.
Red evidence: initial new API tests -> 6 failures for missing models/routes; current-instance subscription regression -> active instead of inactive.
Ruling: preserve the local candidate's current-instance catalog/profile/subscription fixes (3 files), because otherwise rebuilding from main regresses the running site and violates this plan's scope fencing. Cost if wrong: fixtures without engine identity need to be made explicit.
UI: 6 focused tests passed (list URL/search/countdown/batch/detail/focus + overview). typecheck passed; lint only preexisting hook warning and one drawer cleanup warning, cleanup fixed.
Real isolated Miniflux 2.3.3 with synthetic HTTPS fixture: create + reuse old unknown + invalid feed -> PASS. Explicit final parser failure classified without storing upstream diagnostics. Found/fixed duplicate generic convergence after admin recovery.
Final review in progress: fresh reviewer dispatched under executing-plans/requesting-code-review skills. Read-failure proof laundering and unknown subscription regressions observed RED, fixed by preserving admission lineage and rejecting unresolved control outcomes in catalog and personal-ready shortcut.
Local runtime: backup made before 0075; explicit migration applied (startup did not auto-migrate); app/rss-sync same candidate installed. Same Miniflux container restarted after controller stopped. Three old operations resolved via receipt; state/errors/attempts retained; 7 Feed identities preserved.
Browser: default 3 pending + 7 passed; batch submitted through browser/Session/CSRF. WebKit + Martin Fowler connected. Meituan remote Feed exists at /rss.xml, but registered URL /feed/ did not match. Miniflux discover(original) returned exactly /rss.xml: real redirect mismatch, not missing Feed.
Ruling: persist a separately proven same-origin effective_feed_url while preserving original canonical URL and engine/account anchor. Require single Miniflux discovery candidate, exact unique existing Feed, target policy check, lease/snapshot CAS; no same-host guesses or second create. Cost if wrong: redirected sources remain unknown and require manual confirmation; cross-origin aliases deliberately rejected.
Viewport observation: browser was zoomed to 80%; dialog 100vw included scrollbar and extended left. Fix drawer width to 100% and verify true 412 CSS px without retaining browser zoom changes.
