"""Actual Yahoo ^JKSE EOD series, independent of the stock watchlist."""
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from .cloud import SupabaseStore,CloudUnavailable
from .market_news import read
from .providers import finite,retry_transient
from .idx_calendar import eligible_end,session_dates

def benchmark_history(cloud,cutoff=None):
    rows=[]
    for offset in range(0,6000,1000):
        page=read(cloud,'market_benchmark_prices_daily?'+urlencode({'owner_id':'eq.'+cloud.owner,'symbol':'eq.^JKSE',
            'select':'trade_date,open,high,low,close,volume,fetched_at','order':'trade_date','limit':1000,'offset':offset}))
        rows.extend(page)
        if len(page)<1000:break
    if cutoff:
        local=cutoff.astimezone(timezone(timedelta(hours=7)));day=local.date().isoformat()
        rows=[r for r in rows if r['trade_date']<day or (local.hour>=17 and r['trade_date']==day)]
    return rows

def sync_benchmark(cloud=None,force=False):
    import yfinance as yf
    cloud=cloud or SupabaseStore();now=datetime.now(timezone.utc);local=now.astimezone(timezone(timedelta(hours=7)))
    sessions=session_dates((local.date()-timedelta(days=15)).isoformat(),eligible_end(local));expected=sessions[-1]
    previous=benchmark_history(cloud)
    if previous and previous[-1]['trade_date']>=expected and not force:return {'verified':True,'unchanged':True,'rows':len(previous),'last':previous[-1]['trade_date']}
    start=(local.date()-timedelta(days=365*5+7)).isoformat() if not previous else (datetime.fromisoformat(previous[-1]['trade_date']).date()-timedelta(days=7)).isoformat()
    end=(datetime.fromisoformat(expected).date()+timedelta(days=1)).isoformat()
    frame=retry_transient(lambda:yf.Ticker('^JKSE').history(start=start,end=end,auto_adjust=False,actions=False,raise_errors=True))
    if frame is None or frame.empty:raise ValueError('Yahoo ^JKSE returned no OHLCV; old benchmark retained')
    rows=[];rejected=[]
    for index,row in frame.iterrows():
        day=index.date().isoformat()
        if day>expected:continue
        values={k.lower():finite(row.get(k)) for k in ('Open','High','Low','Close','Volume')}
        if any(v is None for v in values.values()) or values['volume']<0 or values['volume']%1:
            rejected.append({'date':day,'reason':'Invalid or missing benchmark OHLCV'});continue
        o,h,l,c=(values[k] for k in ('open','high','low','close'))
        if min(o,h,l,c)<=0 or h<max(o,l,c) or l>min(o,h,c):
            rejected.append({'date':day,'reason':'Inconsistent benchmark OHLC'});continue
        rows.append({'owner_id':cloud.owner,'symbol':'^JKSE','trade_date':day,**values,'volume':int(values['volume']),
            'source':'Yahoo Finance','fetched_at':now.isoformat()})
    if not rows:raise ValueError('No valid benchmark bars; database retained')
    for offset in range(0,len(rows),250):cloud.request('market_benchmark_prices_daily?on_conflict=owner_id,symbol,trade_date',rows[offset:offset+250],prefer='resolution=merge-duplicates,return=minimal')
    checked={r['trade_date']:r for r in benchmark_history(cloud)}
    if any(r['trade_date'] not in checked or any(checked[r['trade_date']][k]!=r[k] for k in ('open','high','low','close','volume')) for r in rows):raise CloudUnavailable('IHSG write readback mismatch')
    return {'verified':True,'rows':len(checked),'received':len(rows),'last':max(checked),'rejected':rejected,
        'missing_sessions':[d for d in session_dates(start,expected) if d not in checked]}
