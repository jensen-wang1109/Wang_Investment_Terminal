"""SMDR-only EOD pilot. All source I/O stays on the backend."""
import csv
import hashlib
import json
import math
import uuid
from datetime import datetime,timedelta,timezone,date
from pathlib import Path
from urllib.parse import urlencode
from .cloud import SupabaseStore,CloudUnavailable
from .contracts import InstrumentRef,PermissionDenied
from .providers import YahooProvider,retry_transient
from .rights import require_rights,ROOT
from .idx_calendar import session_dates,eligible_end

JAKARTA=timezone(timedelta(hours=7))
PILOT='SMDR.JK'

class EodStore(SupabaseStore):
    def prices(self,ticker=PILOT,start='2021-01-01',end='2026-12-31'):
        output=[]
        for offset in range(0,6000,1000):
            params=[('owner_id','eq.'+self.owner),('ticker','eq.'+ticker),('trade_date','gte.'+start),('trade_date','lte.'+end),('order','trade_date'),('limit',1000),('offset',offset)]
            rows=self.request('stock_prices_daily?'+urlencode(params));output.extend(rows)
            if len(rows)<1000:return output
        raise ValueError('Bounded historical response exceeded')

    def logs(self,ticker=PILOT,run_id=None):
        params={'owner_id':'eq.'+self.owner,'ticker':'eq.'+ticker,'order':'started_at.desc','limit':20}
        if run_id:params['run_id']='eq.'+run_id
        return self.request('data_sync_logs?'+urlencode(params))

    def begin(self,report):
        row={k:report[k] for k in ('run_id','ticker','source','trigger','started_at','status')}
        retry_transient(lambda:self.request('data_sync_logs?on_conflict=run_id',[{**row,'owner_id':self.owner}],prefer='resolution=ignore-duplicates,return=minimal'))

    def finish(self,report):
        return retry_transient(lambda:self.request('rpc/finish_idx_sync',{'target_owner':self.owner,'run_identifier':report['run_id'],'run_status':report['status'],'details':report.get('error_details')}))

    def commit(self,report,rows,quality):
        return retry_transient(lambda:self._commit_once(report,rows,quality))

    def _commit_once(self,report,rows,quality):
        try:
            return self.request('rpc/commit_idx_eod',{'target_owner':self.owner,'target_ticker':report['ticker'],'run_identifier':report['run_id'],'price_rows':rows,'validation':quality})
        except CloudUnavailable:
            # A lost response can follow a committed transaction; inspect the log.
            logs=self.logs(report['ticker'],report['run_id'])
            if logs and logs[0]['status'] in ('success','warning'):
                return {k:logs[0][k] for k in ('status','records_inserted','records_updated','records_unchanged')}
            raise

def normalized_row(row,source,fetched_at,reference):
    values={}
    for key in ('open','high','low','close','adjusted_close','volume'):
        value=row.get(key)
        if value in ('',None) and key=='adjusted_close':values[key]=None;continue
        if isinstance(value,bool):raise ValueError('Boolean is not a price or volume')
        number=float(value)
        if not math.isfinite(number):raise ValueError('Non-finite OHLCV value')
        values[key]=number
    if values['volume']<0 or not values['volume'].is_integer():raise ValueError('Volume must be non-negative whole shares')
    values['volume']=int(values['volume'])
    o,h,l,c=[values[k] for k in ('open','high','low','close')]
    if l<=0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError('Inconsistent OHLC values')
    if values['adjusted_close'] is not None and values['adjusted_close']<=0:raise ValueError('Adjusted close must be positive or null')
    day=date.fromisoformat(str(row['trade_date'])).isoformat()
    record={'trade_date':day,**values,'source':source,'fetched_at':fetched_at,'source_reference':reference}
    record['row_hash']=hashlib.sha256(json.dumps({k:v for k,v in record.items() if k!='fetched_at'},sort_keys=True).encode()).hexdigest()
    return record

def validate_rows(rows,start,end,existing=()):
    expected=set(session_dates(start,end));seen=set()
    for row in rows:
        day=row['trade_date']
        if day in seen:raise ValueError('Duplicate trading date in source batch: '+day)
        if day not in expected:raise ValueError('Observation outside eligible IDX sessions: '+day)
        seen.add(day)
    if not rows:raise ValueError('No eligible OHLCV rows returned')
    missing=sorted(expected-seen-{row['trade_date'] for row in existing})
    return {'missing_sessions':missing,'received_rows':len(rows),'expected_sessions':len(expected),
            'calendar':'XIDX 4.13.2 historical + IDX 2026 announcement override',
            'missing_note':'Investigate suspension, listing dates, provider delays or later calendar amendments; not automatically a source error.',
            'zero_volume_sessions':[r['trade_date'] for r in rows if r['volume']==0]}

def import_summary(path,ticker,trade_date=None,volume_unit=None):
    path=Path(path)
    if path.stat().st_size>10*1024*1024:raise ValueError('Summary file exceeds 10 MB')
    if volume_unit not in ('shares','lots'):raise ValueError('Specify whether source volume is shares or lots')
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as stream:raw=list(csv.DictReader(stream))
    elif path.suffix.lower()=='.xlsx':
        from openpyxl import load_workbook
        workbook=load_workbook(path,read_only=True,data_only=True)
        try:
            iterator=workbook.active.values;headers=next(iterator)
            raw=[dict(zip(headers,row)) for row in iterator]
        finally:workbook.close()
    else:raise ValueError('Supported summary formats: CSV or XLSX')
    aliases={'ticker':('ticker','stock code','kode saham'),'trade_date':('trade_date','date','tanggal perdagangan'),
             'open':('open','open price'),'high':('high','highest','tertinggi'),'low':('low','lowest','terendah'),
             'close':('close','close price','penutupan'),'volume':('volume',),'adjusted_close':('adjusted_close',)}
    result=[];fetched=datetime.now(timezone.utc).isoformat()
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    for original in raw:
        lowered={str(k).strip().lower():v for k,v in original.items()}
        row={key:next((lowered[name] for name in names if name in lowered),None) for key,names in aliases.items()}
        symbol=str(row['ticker'] or '').strip().upper().removesuffix('.JK')+'.JK'
        if symbol!=ticker:continue
        day=row['trade_date'] or trade_date
        if isinstance(day,datetime):day=day.date().isoformat()
        row['trade_date']=day
        # No guessed thousands/decimal separator and no inferred prices.
        if volume_unit=='lots' and row['volume'] is not None:row['volume']=float(row['volume'])*100
        result.append(normalized_row(row,'IDX daily summary',fetched,'sha256:'+checksum))
    if not result:raise ValueError('Ticker absent or required summary columns unavailable')
    return result

def run_eod(ticker=PILOT,backfill=False,scheduled=False,summary_file=None,trade_date=None,volume_unit=None,store=None,provider=None,now=None,review=require_rights):
    if ticker!=PILOT:raise ValueError('Only SMDR.JK enabled until the live pilot is verified')
    store=store or EodStore();now=(now or datetime.now(JAKARTA)).astimezone(JAKARTA)
    report={'run_id':str(uuid.uuid4()),'ticker':ticker,'source':'IDX daily summary' if summary_file else 'Yahoo Finance',
            'trigger':'schedule' if scheduled else 'manual','started_at':datetime.now(timezone.utc).isoformat(),'status':'running',
            'records_inserted':0,'records_updated':0,'records_unchanged':0,'source_request_attempted':False}
    log_started=False;phase='database_log'
    try:
        store.begin(report);log_started=True
        phase='calendar'
        if scheduled and (now.hour<17 or not session_dates(now.date().isoformat(),now.date().isoformat())):
            report.update(status='skipped',error_details={'code':'not_an_eligible_collection_session'});store.finish(report);return report
        end=eligible_end(now)
        first=now.date().replace(year=now.year-5) if not (now.month==2 and now.day==29) else date(now.year-5,2,28)
        existing=store.prices(ticker,first.isoformat(),end)
        start=first.isoformat() if backfill or not existing else max(first, date.fromisoformat(existing[-1]['trade_date'])-timedelta(days=7)).isoformat()
        # Revisit older gaps rather than permanently abandoning failed sessions.
        gaps=set(session_dates(first.isoformat(),end))-{r['trade_date'] for r in existing}
        if gaps and existing:start=min(start,min(gaps))
        report.update(window_start=start,window_end=end)
        if summary_file:
            phase='summary_import';rows=import_summary(summary_file,ticker,trade_date,volume_unit)
            start=min(r['trade_date'] for r in rows)
            end=max(r['trade_date'] for r in rows)
            if end>eligible_end(now):raise ValueError('Summary includes a future or unfinished session')
        else:
            phase='source_permission';review('yahoo','retrieve','cache','retain')
            phase='yahoo_history';report['source_request_attempted']=True
            bars=(provider or YahooProvider()).history(InstrumentRef(ticker,'IDX','IDR','Asia/Jakarta'),start,(date.fromisoformat(end)+timedelta(days=1)).isoformat())
            rows=[normalized_row({'trade_date':b.observation_date,'open':b.open,'high':b.high,'low':b.low,'close':b.close,'adjusted_close':b.adjusted_close,'volume':b.volume},'Yahoo Finance',b.fetched_at,'https://finance.yahoo.com/quote/'+ticker+'/history/') for b in bars]
        phase='validation';quality=validate_rows(rows,start,end,existing)
        phase='database_commit';result=store.commit(report,rows,quality);report.update(result,quality=quality)
        phase='database_readback';saved=store.prices(ticker,start,end)
        expected={(r['trade_date'],r['row_hash']) for r in rows}
        actual={(r['trade_date'],r['row_hash']) for r in saved}
        newer={r['trade_date'] for r in saved for submitted in rows if r['trade_date']==submitted['trade_date'] and datetime.fromisoformat(r['fetched_at'].replace('Z','+00:00'))>datetime.fromisoformat(submitted['fetched_at'].replace('Z','+00:00'))}
        if any(day not in newer for day,_ in expected-actual):raise ValueError('Database readback does not match submitted records')
        report.update(database_verified=True,verified_rows=len(rows),source_verified=report['source']=='Yahoo Finance')
    except Exception as error:
        code='provider_permission_required' if isinstance(error,PermissionDenied) else 'sync_failed'
        report.update(status='blocked' if isinstance(error,PermissionDenied) else 'failed',error_details={'code':code,'phase':phase,'error_type':type(error).__name__,'message':str(error) if isinstance(error,(ValueError,PermissionDenied,CloudUnavailable)) else 'Source request failed; inspect provider status, retry transient errors only.'})
        if log_started:
            try:store.finish(report)
            except Exception:report['log_error']='Cloud log update failed; local run artifact retained'
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        destination=ROOT/'.private/research/idx-eod-runs';destination.mkdir(parents=True,exist_ok=True)
        (destination/(report['run_id']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
