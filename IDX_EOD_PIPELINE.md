# IDX EOD pilot

BBCA.JK, SMDR.JK and ADMR.JK. Python/yfinance collects daily unadjusted OHLCV with adjusted close when available. Supabase PostgreSQL stores the result; the frontend never calls Yahoo. The SMDR pilot passed real source, insert and database readback verification on October 18, 2026; BBCA and ADMR then passed the same checks.

## Deployment

1. Apply `supabase/migrations/202610160007_idx_eod.sql` to the existing project's `investment` schema. This migration is additive; it does not delete legacy observations. The schema must already be exposed in Supabase Data API settings, and the configured owner must exist in `auth.users`.
2. Configure repository Actions Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (also accepts a Supabase modern secret key), and `WANG_SUPABASE_OWNER_ID`. Never add these to frontend variables or commit them. This daily-price adapter implements the user's explicit personal-use download request. No rights manifest is fabricated, and this does not approve ML training or change unrelated data adapters.
3. Run the workflow **IDX Daily EOD** manually with `backfill=true`. Its schedule is `0 10 * * 1-5`, or 17:00 Asia/Jakarta. GitHub can delay scheduled execution; the computer need not stay on. Only this EOD workflow is deployed; the local legacy scheduler is separate.
4. Check the run artifact and the database. `database_verified=true` requires a matching database readback, not just HTTP success. Missing sessions produce `warning` and a failing job for review. Failures do not overwrite existing valid prices. A failure during readback retains committed counts and marks verification failed.

## Local commands

```sh
python -m pip install -r services/research_api/requirements-eod.txt
python scripts/sync-idx-eod.py --backfill
python scripts/sync-idx-eod.py
python -m unittest discover -s tests -p test_idx_eod.py
```

The runner loads recognized server settings from `.env.local` or process environment. Private run reports are stored under `.private/research/idx-eod-runs/`. No credentials are included. The API supports `GET /api/v1/eod/prices?symbol=SMDR.JK&start=2021-10-16&end=2026-10-16`, `GET /api/v1/eod/status`, and token-protected `POST /api/v1/eod/sync` with `{"symbol":"SMDR.JK","backfill":true}`. Use the symbol parameter for any of the three enabled tickers. The existing local app server includes these routes; it is a loopback development service, not an internet-authenticated production API. Its stock detail chart also reads the new daily table for all three tickers.

## Fallback file import

Download an authorized IDX daily trading summary yourself and keep the original file. CSV or XLSX is supported; ticker, date, open, high, low, close and volume are required. Headers may include `Stock Code`, `Open Price`, `Highest`, `Lowest`, `Close`, `Volume`. If the file has no trade-date column, supply `--trade-date`. Explicitly identify volume units; a lot equals 100 shares. Numeric separators are not guessed. Files are limited to 10 MB. The SHA-256 of the source file is recorded with the imported observations.

```sh
python scripts/sync-idx-eod.py --import-summary /path/to/idx-summary.xlsx --trade-date 2026-10-16 --volume-unit shares
python scripts/sync-idx-eod.py --fallback-file /path/to/idx-summary.csv --trade-date 2026-10-16 --volume-unit shares
```

Fallback uses a supplied file and a separate logged run; it does not bypass IDX access controls or fabricate adjusted prices. The GitHub workflow does not scrape or automatically acquire IDX files.

## Data integrity and calendar

- Primary key `(ticker, trade_date)` prevents duplicates. Atomic RPC upserts count inserts, updates and unchanged records under a per-ticker transaction lock. Invalid rows roll back the entire batch. Newer observations are preserved against older imports.
- Five-year initialization, seven-day overlap for incremental refresh, and revisiting unresolved historical gaps. Use manual backfill to re-fetch older corporate-action adjustments.
- Reject empty responses, duplicate dates, invalid/non-finite/negative prices, inconsistent OHLC and non-integer/negative volume. Missing expected trading sessions and zero-volume sessions remain visible for investigation, including possible suspensions.
- XIDX from pinned exchange-calendars covers 2021–2025; `config/idx-calendar-2026.json` overrides 2026 with the IDX announcement, 239 sessions. The checked-in amendments also remove four Eid leave dates in 2022 and August 18, 2025. ADMR starts on its issuer-confirmed listing date January 3, 2022, so pre-listing days are not missing. Review amendments and the 2027 calendar before extending coverage; later years fail closed rather than assuming weekday sessions.
- Retries use exponential delays for timeouts and HTTP 500/502/503/504. HTTP 401/403/429 stop without circumventing source restrictions. Interrupted jobs may leave `running` logs, which must be checked alongside the GitHub run state.

## Verification queries

```sql
select ticker,count(*) as bars,min(trade_date),max(trade_date)
from investment.stock_prices_daily where ticker='SMDR.JK' group by ticker;
select trade_date,open,high,low,close,adjusted_close,volume,source,fetched_at
from investment.stock_prices_daily where ticker='SMDR.JK' order by trade_date desc limit 10;
select run_id,status,started_at,finished_at,records_inserted,records_updated,error_details,quality
from investment.data_sync_logs where ticker='SMDR.JK' order by started_at desc limit 10;
```

An empty result is not a successful price sync. Unit tests use synthetic fixtures isolated from production. Only actual source responses and database queries can satisfy the live acceptance criteria.
