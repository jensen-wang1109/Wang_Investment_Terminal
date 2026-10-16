"""Bounded XIDX sessions: historical library plus the reviewed 2026 announcement."""
import json
from datetime import date,timedelta
from functools import lru_cache
from .rights import ROOT

@lru_cache(maxsize=1)
def sessions():
    import exchange_calendars as calendars
    import pandas as pd
    calendar=calendars.get_calendar('XIDX',start='2021-01-01',end='2026-12-31')
    historical={d.date().isoformat() for d in calendar.sessions if d.year<2026}
    record=json.loads((ROOT/'config/idx-calendar-2026.json').read_text())
    current={d.date().isoformat() for d in pd.date_range('2026-01-01','2026-12-31',freq='B')} - set(record['holidays'])
    if len(current)!=record['expected_sessions']:raise ValueError('Calendar checksum/session count mismatch')
    return historical|current

def session_dates(start,end):
    if start<'2021-01-01' or end>'2026-12-31':raise ValueError('Calendar coverage is 2021–2026; review the next IDX holiday announcement before extending it')
    if start>end:return []
    return sorted(day for day in sessions() if start<=day<=end)

def eligible_end(now):
    # A manual run before the 17:00 WIB collection time excludes today's bar.
    end=now.date() if now.hour>=17 else now.date()-timedelta(days=1)
    return end.isoformat()
