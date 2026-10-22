"""Personal Yahoo research snapshots. All source I/O stays on the server.

Independent module failures preserve previous successful values and timestamps.
No cookie/identity rotation or retries on access denials / rate limiting.
"""
import json
import threading
import time
import uuid
from datetime import datetime,timezone
from urllib.parse import urlparse,urlencode
from .cloud import SupabaseStore,CloudUnavailable
from .providers import retry_transient,finite
from .stock_details import normalize_info
from .repository import now_iso
from .rights import ROOT
from .infrastructure import atomic_json,read_json

STATUS_FILE=ROOT/'.private/research/stock-enrichment-status.json'
_lock=threading.Lock()
_thread=None

class ResearchAccessDenied(Exception):
    def __init__(self,status):
        super().__init__('Yahoo source access rejected')
        self.status_code=status

from .providers import access_status


def safe_url(value):
    if not isinstance(value,str):return None
    parsed=urlparse(value)
    return value if parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and not parsed.password else None

def holder_rows(frame):
    if frame is None or frame.empty:return []
    # pandas converts NaN/NaT to null and dates to ISO strings.
    return json.loads(frame.head(100).to_json(orient='records',date_format='iso'))

def news_rows(items,symbol):
    result=[];seen=set()
    if not isinstance(items,list):raise ValueError('Invalid Yahoo news response')
    for item in items:
        content=item.get('content',item) if isinstance(item,dict) else {}
        title=content.get('title')
        url=safe_url((content.get('canonicalUrl') or {}).get('url') if isinstance(content.get('canonicalUrl'),dict) else content.get('link'))
        if not url:url=safe_url((content.get('clickThroughUrl') or {}).get('url') if isinstance(content.get('clickThroughUrl'),dict) else None)
        if not title or not url or url in seen:continue
        # Old Yahoo responses expose relatedTickers; reject unrelated articles.
        related=item.get('relatedTickers')
        if related and symbol not in related:continue
        published=content.get('pubDate')
        if not published and isinstance(content.get('providerPublishTime'),(int,float)):
            published=datetime.fromtimestamp(content['providerPublishTime'],timezone.utc).isoformat()
        provider=content.get('provider') or {}
        seen.add(url)
        result.append({'title':str(title)[:1000],'url':url,'publishedAt':published,
            'publisher':provider.get('displayName') if isinstance(provider,dict) else None,
            'relevance':'Yahoo ticker feed','symbol':symbol})
    return result[:20]

def collect_research(ticker,symbol,previous=None,sleep=time.sleep):
    old=previous or {}
    profile=dict(old.get('profile') or {});metrics=dict(old.get('metrics') or {})
    modules=dict(profile.get('moduleStatus') or {});blocked=False;any_success=False;access_code=None
    if old.get('retrieved_at') and not modules.get('profile'):
        modules['profile']={'last_success_at':old['retrieved_at']}
    fetched=now_iso()
    def run(name,call,save):
        nonlocal blocked,any_success,access_code
        if blocked:
            modules[name]={**modules.get(name,{}),'status':'skipped','attempted_at':fetched,'reason':'Source access rejected; remaining requests stopped'}
            return
        sleep(1)
        try:
            value=retry_transient(call,sleep=sleep)
            nonempty=save(value)
            any_success=True
            modules[name]={'status':'available' if nonempty else 'empty','attempted_at':fetched,
                'last_success_at':fetched,'reason':None if nonempty else 'Yahoo returned no records for this ticker'}
        except Exception as error:
            code=access_status(error);blocked=code in (401,403,429)
            if blocked:access_code=code
            modules[name]={**modules.get(name,{}),'status':'failed','attempted_at':fetched,
                'reason':'Source access rejected' if blocked else 'Yahoo module could not be retrieved',
                'error_type':type(error).__name__,'http_status':code if isinstance(code,int) else None}

    def save_info(info):
        if info.get('symbol','').upper()!=symbol:raise ValueError('Yahoo ticker mismatch')
        normalized=normalize_info(info)
        if not any(v is not None for v in normalized['metrics'].values()):raise ValueError('No statistics returned')
        profile.update(normalized['profile']);metrics.clear();metrics.update(normalized['metrics'])
        return True
    run('profile',ticker.get_info,save_info)
    modules['statistics']=dict(modules['profile'])
    def save_valuation(frame):
        from .yahoo_valuation import apply_price_book
        return apply_price_book({'profile':profile,'metrics':metrics},frame,fetched)
    previous_pbv=(old.get('profile') or {}).get('metricProvenance',{}).get('priceToBook')
    if previous_pbv and previous_pbv.get('status')=='verified_valuation_table':metrics['priceToBook']=old.get('metrics',{}).get('priceToBook')
    else:metrics['priceToBook']=None
    run('valuation',lambda:ticker.valuation,save_valuation)
    ownership=dict(profile.get('ownership') or {})
    def save_major(frame):
        if frame is None or frame.empty:return False
        ownership['major']={str(k):finite(v) for k,v in frame.iloc[:,0].items()}
        ownership['major_as_of']=fetched;return True
    run('major_holders',ticker.get_major_holders,save_major)
    def save_holders(frame,key):
        values=holder_rows(frame)
        if values:ownership[key]=values;ownership[key+'_as_of']=fetched
        return bool(values)
    run('institutional_holders',ticker.get_institutional_holders,lambda frame:save_holders(frame,'institutions'))
    run('mutualfund_holders',ticker.get_mutualfund_holders,lambda frame:save_holders(frame,'funds'))
    profile['ownership']=ownership
    def save_news(items):
        values=news_rows(items,symbol)
        if values:profile['news']=values;profile['news_as_of']=fetched
        return bool(values)
    run('news',lambda:ticker.get_news(count=20),save_news)
    profile['moduleStatus']=modules
    if not any_success and not old:
        if blocked:raise ResearchAccessDenied(access_code)
        raise ValueError('No verified Yahoo modules; no empty snapshot saved')
    if not profile.get('symbol'):profile['symbol']=symbol
    return {'profile':profile,'metrics':metrics,'statements':[],
        'retrieved_at':fetched,'basis':'Yahoo research snapshot; quote/reporting currencies separate; module timestamps identify cached data',
        'access_rejected':blocked,'status':'partial' if any(m['status'] in ('failed','skipped') for m in modules.values()) else 'success'}

def run_enrichment(symbols=None,cloud=None,sleep=time.sleep,progress=None,ticker_factory=None):
    cloud=cloud or SupabaseStore()
    active=cloud.tracked()
    if symbols is None:symbols=active
    if not isinstance(symbols,list) or not symbols or len(symbols)>200 or any(s not in active for s in symbols):raise ValueError('Pilih 1–200 saham aktif')
    symbols=list(dict.fromkeys(symbols))
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory=yf.Ticker
    report={'id':str(uuid.uuid4()),'status':'running','started_at':now_iso(),'total':len(symbols),'completed':0,'results':[]}
    def emit():
        if progress:progress(report)
    emit();consecutive_failures=0;stop=False
    for symbol in symbols:
        started=now_iso();entry={'symbol':symbol,'status':'skipped'}
        if stop:entry['reason']='Circuit breaker; retry later'
        else:
            try:
                previous=cloud.detail_state(symbol)
                previous=cloud.stock_details(symbol)['company'] if previous else None
                details=collect_research(ticker_factory(symbol),symbol,previous,sleep)
                saved=cloud.save_stock_details(symbol,details)
                checked=cloud.request('current_stock_company_snapshots?'+urlencode({'owner_id':'eq.'+cloud.owner,'symbol':'eq.'+symbol,'select':'revision_hash,profile,metrics','limit':1}))
                if not checked or checked[0]['profile']!=details['profile'] or checked[0]['metrics']!=details['metrics']:
                    raise CloudUnavailable('Snapshot database readback mismatch')
                entry.update(status=details['status'],verified=True,metrics=sum(v is not None for v in details['metrics'].values()),modules=details['profile']['moduleStatus'],saved=saved)
                stop=details['access_rejected'];consecutive_failures=0
            except Exception as error:
                entry.update(status='failed',reason='Source retrieval or database write/readback failed; previous valid data retained',error_type=type(error).__name__)
                consecutive_failures+=1;stop=access_status(error) in (401,403,429) or consecutive_failures>=3
        try:
            cloud.request('stock_research_sync_logs',{'run_id':str(uuid.uuid4()),'owner_id':cloud.owner,'symbol':symbol,'status':entry['status'],'started_at':started,'finished_at':now_iso(),'details':entry})
        except CloudUnavailable:
            entry['log_warning']='Cloud sync log unavailable; local job log retained'
        report['results'].append(entry);report['completed']+=1;emit()
        if not stop:sleep(2)
    report.update(status='completed' if all(r['status']=='success' for r in report['results']) else 'completed_with_issues',finished_at=now_iso())
    emit();return report

def enrichment_status():
    report=read_json(STATUS_FILE,{'status':'idle','results':[]})
    if report.get('status')=='running' and not (_thread and _thread.is_alive()):
        report={**report,'status':'interrupted','reason':'Server restarted; completed snapshots are preserved'}
    return report

def start_enrichment(symbols=None):
    global _thread
    with _lock:
        if _thread and _thread.is_alive():return enrichment_status()
        cloud=SupabaseStore();active=cloud.tracked()
        symbols=active if symbols is None else symbols
        if not isinstance(symbols,list) or not symbols or len(symbols)>200 or any(not isinstance(s,str) or s not in active for s in symbols):raise ValueError('Pilih saham aktif dari Stocklist')
        atomic_json(STATUS_FILE,{'status':'running','started_at':now_iso(),'total':len(symbols),'completed':0,'results':[]})
        def work():
            try:run_enrichment(symbols,cloud=cloud,progress=lambda r:atomic_json(STATUS_FILE,r))
            except Exception as error:atomic_json(STATUS_FILE,{'status':'failed','error_type':type(error).__name__,'reason':'Research synchronization could not complete'})
        _thread=threading.Thread(target=work,daemon=True);_thread.start()
        return read_json(STATUS_FILE)
