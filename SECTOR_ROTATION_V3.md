# Macro-driven sector rotation

The active methodology is `sector-macro-rotation-v3.0`. Company fundamentals,
valuation ratios, business summaries and earnings revisions are not scoring inputs.
The user selects individual companies after assessing the industry thesis.

## Research score

Configure `config/sector-intelligence.json`: macro alignment 25%, commodity/leading
indicators 20%, relative strength 20%, momentum/trend 15%, breadth 10%, risk/volatility 10%.
Weights must be finite, positive and total 100. Missing metrics are excluded and
available weights normalized. Scores are research scores, never return probabilities.

Independent official macro/commodity observations and reviewed external evidence
support macro reasoning. Internal headlines may start research sessions but their
count cannot fill missing numerical factors. The economic transmission library is
a set of falsifiable hypotheses; it does not establish issuer revenue exposure.

Relative strength uses actual Yahoo `^JKSE` closing prices and the same observed
21/63/126-session endpoints for representatives. Price returns exclude dividends
on both sides. Trend uses available MA20/50/200 checks, acceleration and prior
20-session high breakouts. Breadth counts available positive trends. Risk includes
annualized daily volatility, trailing maximum drawdown and MA reversal risk.
Absent endpoint observations are not interpolated. Source revisions remain a limit.

## Coverage and publication

Data Coverage Confidence is separate: stock count 35% (capped at three), historical
completeness/depth/availability 40%, equal-weight diversification proxy 25%.
It measures the personal representative set, not full IDX industry coverage.
At least two representatives and complete 1/3/6-month IHSG comparisons are required
for beneficiary publication. An isolated stock does not confirm an industry rotation.

Available factor weight, confidence and macro alignment gates are configurable.
Price extensions (default >20% above MA50, >30% in 21 sessions or >60% in 63 sessions)
block the shortlist. Emerging, confirmed and extended trends are shown separately.
A global shortlist contains at most three industries and can be empty. Conditional
adverse transmission and price-pressure rankings are distinct from beneficiary
conviction and are not short-sale instructions.

Existing immutable revisions, evidence lineage, event-based notification rules,
cooldowns, urgent invalidations and revision-specific PDF downloads remain intact.
Archived reports retain their original methodology.

## Diagnostics

`python scripts/validate-sector-rotation.py` computes chronological monthly technical
diagnostics against IHSG with fixed configured weights and an explicit assumed
round-trip cost. It excludes single-stock industries. It is NOT a backtest of the
combined macro model: historical release vintages are missing. Current watchlist
selection, survivorship, overlapping horizons, revisions, execution and dividends
are limitations. Weights are not optimized from this diagnostic. No successful
forecast claim is made. The existing failed legacy price ML remains gated.

## Data updates

* IDX EOD workflow: daily prices and independent IHSG benchmark after 17:00 WIB.
* Market News: 08:00 WIB daily and 17:15 WIB on exchange sessions. Morning reports
  include source publications up to 08:00. Collection time is recorded separately:
  delayed collection is not represented as information already known at 08:00.
  IHSG is mandatory in the domestic discussion; unavailable evidence is explicit.
* Research Accuracy: Current Price/Book after 18:00 WIB on weekdays; annual/quarterly
  financial statements Saturday 08:00 WIB, and manual dispatch.
* Sector monitor: keeps existing event-led checks. Refreshing data does not force a
  new thesis or notification. GitHub scheduled jobs may be delayed.

PBV uses Yahoo's valuation table `Price/Book` / `Current`, with field provenance and
retrieval time. The `get_info()` PBV can mix quote and book-value currencies. It is
never used as fallback. Unverified mixed-currency EV/sales/EBITDA fields are hidden
on API read while raw source snapshots remain preserved. Financials retain only
actual periods within five years; a missing period is never generated.

Server credentials stay in existing server environment and GitHub Actions Secrets.
The frontend reads Supabase through the internal API; it never calls Yahoo directly.
