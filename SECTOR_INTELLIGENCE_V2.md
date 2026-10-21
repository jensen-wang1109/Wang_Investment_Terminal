# Sectoral Intelligence Engine 2.0

Upgrade 21 October 2026. Existing daily Analyzer, price collection, Stocklist,
Sector tree, calculators and ML evaluation remain separate working features.

## Implemented architecture

`fetch-macro.py` -> cached official source files / normalized observations ->
shared Supabase `sector_macro_context` vintage -> deterministic regime analytics ->
conditional industry graph -> six-factor evidence checks -> internal evaluation ->
material publication transaction -> immutable revisions + existing notification inbox.

The analytical sequence is **macro -> economic transmission -> industry ->
earnings -> market repricing**. Industry growth, issuer profitability and an
underpriced stock are three separate propositions.

The existing card design is retained. The principal shortlist contains at most
three distinct industries across all sessions. Zero is a valid result. Draft
sessions show their blockers, observed values, two-sided effects, causal sequence,
conditional scenarios, issuer exposure status and source timestamps. Legacy
headline cards remain in an explicitly marked archive.

## Provenance and regimes

Official values preserve source URL, observation period, collection time, checksum,
native frequency, unknown publication / availability timestamps and unknown
revision status. Economic periods never become fabricated release dates.
Failed downloads retain the prior snapshot and expose their status.

The collector now includes World Bank silver, aluminium, tin, US / European gas,
Japan LNG and wheat. US CPI and industrial production have FRED adapters; these
new connections did **not** return usable CSV during the local verification.
Previously stored FRED values remain available and dated. China credit, licensed
PMI, inventory / freight, credit growth and domestic sector GDP remain coverage gaps.

Deterministic analytics calculate changes, acceleration, daily change z-scores,
and native-cadence freshness. Combined financing regimes examine rates with FX,
inflation and yields. The yield curve uses same-date 10Y minus 2Y. These are
transparent heuristics, not fitted regime classifiers or recession forecasts.

## Causal / issuer checks

The initial hypothesis library covers energy, AI power capex, gold, food, domestic
rates, shipping disruption and nickel capacity. Exact industry mappings come
from the existing database; no new stock universe is imported.

AI is mapped to data centers and electrical/cables. Tin, chemicals and all metal
miners are not automatically selected. Shipping requires vessel / route / contract
economics; oil is not palm oil; thermal coal is not coking coal. Gold is not used
as a stand-alone bank sell signal. Nickel production growth does not imply margin growth.

Yahoo business-summary product matches are labelled **business only** until a
reviewed filing establishes material earnings exposure. P/E and PBV snapshots
are context, not proof of undervaluation. Relative returns compare current
watchlist baskets, not official IDX sector indices or IHSG. Capital flows are
not inferred from trading volume.

New causal discovery by an LLM is **not configured**. Unknown numerical anomalies
are recorded as research questions, not new causal facts. The graph can be
extended in code after evidence review; the system does not claim that its
fixed initial mechanisms were discovered or learned from headlines.

## Conviction and missing inputs

Weights in `config/sector-intelligence.json`:

| Factor | Weight |
|---|---:|
| Macro alignment | 20 |
| Supply-demand balance | 20 |
| Earnings improvement | 25 |
| Policy / catalyst | 10 |
| Valuation / expectations | 15 |
| Relative strength | 10 |

Factor values range 0–100. Unknown factors remain null. The conservative total
contributes zero for missing factors **without reweighting** available ones;
this is not a prediction that the missing economic effect equals zero. Data
coverage and data quality are displayed separately. Unknown release clocks reduce
data quality. Weights and thresholds are provisional, uncalibrated research priors.

Publication requires score >=80 (configurable), data quality >=80, complete
supply-demand / earnings / valuation evidence, verified material issuer exposure,
fresh numeric macro confirmation, and current price/liquidity coverage. Narrative
headlines cannot fill these missing factors. Scores are **not probabilities**.

Structured evidence is append-only in `sector_evidence_assertions`. A reviewed
record requires event, industry, factor, score, original source URL and excerpt,
reviewer, measurement basis, publication and collection clocks, observation date,
expiry, credibility and reasoning. Earnings exposure is ticker-specific.

`python scripts/review-sector-evidence.py FILE.json` validates only (default).
`--save-cloud` persists reviewed records and verifies readback. Revised evidence
must use a new ID. This tool never downloads arbitrary input URLs. No research
evidence or high scores were fabricated to populate the application.

## Publication and history

Data refresh, internal reevaluation and public thesis publication are separate.
Current numeric/supporting evidence updates internally without rewriting the
last published revision. Identical evaluations are cached by content hash.
Meaningful status, eligibility or configured score changes can publish; a normal
72-hour cooldown applies. Verified invalidation, material policy and loss of
execution gates can bypass cooldown. A methodology-only version change does not
create investment notices. Exact normalized headline duplicates are assigned to
one event only. Reviewed contradictory industry evidence vetoes global ranking.

Migration 011 adds only three entities: internal evaluations, immutable published
thesis revisions, and reviewed evidence assertions. Existing source, price, macro,
model and notification tables are reused. RLS limits authenticated reads to the
owner. Only the server publication RPC writes thesis history and notifications,
in one advisory-locked transaction. Frontend receives no server key.

Published revisions support exact-version PDF downloads, two A4 pages, actual
observation chart, causal sequence, industries, scenarios, risks, monitoring and
clickable sources. Missing chart data is explicitly stated. Internal drafts do
not masquerade as published theses or generate alerts.

APIs:

- `GET /api/v1/sector-intelligence`
- `GET /api/v1/sector-intelligence?session_id=v2_energy&revision=1`
- `GET /api/v1/sector-intelligence/pdf?session_id=v2_energy&revision=1`
- Existing `POST /api/v1/sector-trends/refresh` launches the monitor.

Existing five daily GitHub monitor windows remain (WIB 07:30, 10:30, 13:30,
16:30, 19:30). Macro collection runs in the morning and on manual dispatch.
The upgraded monitor replaces legacy headline-driven publication. Daily market
briefs retain their own daily / close schedule, separately from sector theses.

## Historical validation limits

The existing price-only model remains research-only: all 1/3/6-month horizons
failed the earlier out-of-sample baseline comparison. This upgrade does not relabel
that model as validated or retrain it with revised macro data as if known earlier.
The model's actual loss, bias, calibration and purged walk-forward results remain
visible. No alpha, Sharpe or drawdown result is claimed for this new engine.

COVID, the energy crisis, shipping, nickel oversupply, AI and policy cases are a
mechanism library, not point-in-time training labels. A genuine hybrid backtest
still requires reconstructed publication vintages, historical industry membership,
issuer-level exposure / expectations, official benchmarks and executable cost
assumptions. No current survivor basket can remove those gaps by itself.

## Verification

Local Supabase migration succeeded. A real run persisted 28 series and six
internal sessions with **zero eligible industries / zero new publications**;
readback and internal API queries succeeded. A real-data two-page PDF was rendered
and visually reviewed as an explicitly unpublished internal preview.

Isolated scenario tests cover the ten requested acceptance cases; synthetic
scenarios are never loaded into production. A database transaction test confirmed
atomic publication / notifications, duplicate suppression, cooldown, urgent
invalidation, immutable revisions and permission isolation, then rolled back all
test records. Full regression initially passed 115 Python tests, 27 JS tests,
TypeScript and Vite production build. See the final task report for later checks.

Reference mechanisms were checked against the IEA Energy and AI report and the
IEA Global Critical Minerals Outlook 2025. These support mechanism hypotheses;
their scenarios do not verify current Indonesian issuer earnings or stock upside.
