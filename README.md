# Wang Investment Terminal — Daily IDX EOD

Python/yfinance daily-price ingestion for the existing private Investment Intelligence Platform. The scheduler reads the active watchlist from Supabase after market close and verifies each upsert by reading it back. See [setup, integrity checks and API integration](IDX_EOD_PIPELINE.md).

This repository contains the minimal scheduler/collector package. Personal watchlists, credentials, local frontend research and individual run artifacts remain private.
