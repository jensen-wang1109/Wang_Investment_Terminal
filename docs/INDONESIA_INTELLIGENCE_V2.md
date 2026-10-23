# Indonesia-first shared intelligence V2

The existing React/Vite app, owner-scoped Supabase integration, watchlist, and native historical charts are retained. Macro Analyzer now presents five primary sections. Detailed evidence and limitations are expandable. The daily PDF uses the exact persisted report and remains two pages for the verified report.

## Analytical pipeline

Official macro releases + FRED daily yields / broad USD + dated ADB Indonesia government yields + identity-checked EOD prices + domestic publisher headlines → timestamp / completeness checks → shared market features and event materiality → independent economic / equity regimes → IHSG and rupiah assessment → conditional industry exposure mapping → selective industry conviction → append-only reports and evaluation memory.

One topic classifier is reused. It is trained on small educational topic scenarios, not future investment returns. Current return forecasting is a heuristic framework, not a trained or statistically optimized model.

## Daily data

- Native charts open at 1 month.
- Treasury 2Y / 10Y: FRED DGS2 / DGS10, percent yield; broad USD: DTWEXBGS. Broad USD is not DXY.
- DXY: separate DX-Y.NYB instrument with identity verification, backend collection only.
- SBN local-currency government benchmark yields: AsianBondsOnline / ADB, tenors 2 / 5 / 10 years. Store the page's Close of date, never the retrieval date. First verified observation is 21 October 2026: 6.925%, 7.225%, 7.421%. No historical SBN backfill is fabricated.
- Daily rate observations are upserted through economic_observations with revision lineage and verified readback. A source outage retains old observations and their dates.
- /api/v1/macro/dataset reads the cloud history and merges compatible official snapshots; the frontend does not fetch external market APIs.

## Publication and persistence

The unified GitHub workflow runs at 19:00 WIB / 20:00 Perth every calendar day. GitHub can queue jobs, so execution is not guaranteed to the exact minute. Before 19:00, a manual run is a preview; it does not suppress the scheduled evening report. Scheduled reports are idempotent by Jakarta date. Weekends and verified IDX holidays produce a shorter, dated report. The reviewed exchange calendar covers 2021–2026 and must be updated before 2027.

Separate news jobs collect headlines only. The former multiple scheduled sector runs are removed; manual sector reassessment remains available. Market collection may run independently without publishing duplicate daily analysis.

Ordinary regime switches require two distinct daily observations. Missing evidence is reported immediately rather than retaining false confidence. Industry publishing additionally requires material evidence, multi-stock coverage, a verified catalyst and price checks. Repeated same-day refreshes cannot satisfy persistence. Existing revision transaction, cooldown, PDF and notification deduplication remain in use.

## Scoring

Provisional configurable research weights: Indonesia macro alignment 30%, industry drivers 25%, price confirmation 20%, catalyst strength 15%, evidence quality / consistency 10%. Missing factors are excluded and reduced included weight is disclosed. Data Coverage Confidence remains separate. No company fundamentals are used. Price-only archived diagnostics retain their old internal technical weights and are never represented as validation of the new combined macro model.

Maximum three beneficiary industries and three adverse industries. Early Opportunity requires a plausible verified catalyst and economic support; strong momentum alone is insufficient. One stock is not an industry. Published close-price outcomes use frozen publication membership and next-session entry against actual IHSG at 21 / 63 / 126 sessions. Missing endpoints cannot become zero returns or successful predictions.

## Memory and storage

Reuse daily_market_analysis, sector_macro_context, sector_intelligence_evaluations, sectoral_thesis_revisions, sector_notifications, economic_observations and ingestion_runs. New context kinds namespace monthly structured summaries, prediction outcomes and memory audits; no duplicate stock database is created.

Monthly summaries retain structured dates / regimes / index / FX / quality. Mature outcomes remain append-only with coverage and model version. No new return model is trained until enough point-in-time labels and independent out-of-sample baseline validation exist. Current mature outcome sample count is zero; no predictive accuracy is claimed.

Actual project billing was checked on 23 October 2026: Free plan, 500 MB database quota. Dashboard showed 122.9 MB database usage at inspection, separate from WAL / system / provisioned disk. The existing 350 MB conservative working budget is not the plan quota. Settings remain configurable and should be reviewed after plan changes.

Retention policy defaults: raw cache 14 days, detailed reports 90 days, operational logs 30 days. Cloud cleanup currently runs in preview mode; nothing irreversibly deletes research history. Long-term indicator observations, structured daily / monthly states, thesis revisions and outcomes are preserved. No monthly wipe. This mode is explicitly reported in memory audit output.

## Gaps

Fresh M2, credit, consumption / industrial releases, trade / current account, reserves, foreign flows, official IDX breadth and concentration are not all connected. Do not infer a confident economic cycle from quarterly GDP alone. Claims inferred from headlines remain unverified and cannot become high-impact confirmed events just because many publishers repeat them. Event clustering is deliberately conservative and can merge distinct same-day driver events; it is not autonomous semantic fact verification.

## Verification

Actual local end-to-end run saved and read back a V2 macro report and linked sector evaluation from Supabase, with IHSG and USD/IDR observations through 22 October 2026. No new high-conviction sector thesis was forced. All 176 backend tests and 28 frontend tests passed before deployment; TypeScript check passed. PDF rendered as two pages and visually inspected. Deployment / workflow outcome must be verified separately from local success.

## Primary publisher fallback verified after CI transport failure

The first GitHub run completed but its FRED requests timed out; prior data was retained and the rate stage reported partial status. The collector now prefers the official US Treasury XML curve for current 2Y / 10Y yields and the Federal Reserve H10 table for the broad USD index. FRED remains a fallback. The H10 table publishes daily observations in a weekly release, so daily polling does not invent newer observations between releases. Fed target levels are independently checked against the official policy changes table, using the actual effective date. Provenance is recorded on each observation through a source-specific quality flag; DXY remains a separate instrument.

The primary publisher path was also tested from GitHub Actions: all Treasury / broad USD / Fed policy / SBN source results passed database readback. A legacy benchmark logging error on boolean unchanged markers was corrected to integer counters and verified against the live database.
