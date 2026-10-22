"""Server-only, identity-checked market EOD history and commodity snapshots."""
import hashlib,json,os,time,uuid
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode,quote
from urllib.request import Request
from zoneinfo import ZoneInfo
from .cloud import SupabaseStore,CloudUnavailable
from .market_news import read
from .network import secure_open
from .providers import finite,retry_transient,access_status
from .rights import ROOT

CONFIG=ROOT/'config/market-instruments.json'
CACHE=ROOT/'.private/market-data'

def catalogue():return json.loads(CONFIG.read_text(encoding='utf8'))
def instrument(symbol):
    item=next((i for i in catalogue() if i['symbol']==symbol),None)
    if item is None:raise ValueError('Instrumen tidak terdaftar')
    return item

def checksum(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()

def last_completed_day(meta,now):
    local=now.astimezone(ZoneInfo(meta['exchangeTimezoneName']))
    # No today's bar unless the source explicitly places the regular close in the past.
    end=meta.get('currentTradingPeriod',{}).get('regular',{}).get('end')
    close=end.astimezone(timezone.utc) if isinstance(end,datetime) and end.tzinfo else datetime.fromtimestamp(end,timezone.utc) if isinstance(end,(int,float)) else None
    closed=bool(close and close.astimezone(local.tzinfo).date()==local.date() and close+timedelta(minutes=30)<=now)
    return (local.date() if closed else local.date()-timedelta(days=1)).isoformat()

def normalize_history(item,frame,meta,now):
    if meta.get('symbol')!=item['symbol'] or meta.get('instrumentType') not in item.get('source_kinds',[item['kind']]):
        raise ValueError('Source instrument identity mismatch; no substitute ticker accepted')
    if not meta.get('exchangeTimezoneName'):raise ValueError('Source exchange timezone missing')
    # Prices in US cents are sometimes described as USD by the futures vendor.
    if meta.get('currency') not in ({item['currency'],'USD'} if item['currency']=='USX' else {item['currency']}):
        raise ValueError('Source currency mismatch')
    limit=last_completed_day(meta,now);result=[];seen=set();rejected=0
    for timestamp,row in frame.iterrows():
        day=timestamp.date().isoformat()
        if day>limit:continue
        if day in seen:raise ValueError('Duplicate source session')
        seen.add(day)
        values={k.lower():finite(row.get(k)) for k in ('Open','High','Low','Close')}
        vol=finite(row.get('Volume'));adj=finite(row.get('Adj Close'))
        if any(v is None for v in values.values()):rejected+=1;continue
        o,h,l,c=(values[k] for k in ('open','high','low','close'))
        if item['kind']=='CURRENCY' and c>0:
            # FX is a daily exchange-rate series, not exchange-traded volume.
            # Bad OHLC fields do not invalidate a positive source closing rate;
            # explicitly omit those fields rather than repair their values.
            if h<max(o,l,c) or l>min(o,h,c):o=h=l=None
            vol=None
        elif c<=0 or h<max(o,l,c) or l>min(o,h,c) or (vol is not None and (vol<0 or vol%1)):
            rejected+=1;continue
        point={'observation_date':day,'value':c,'open':o,'high':h,'low':l,'adjusted_close':adj,
               'volume':int(vol) if vol is not None else None,'published_at':None,'available_at':now.isoformat(),
               'retrieved_at':now.isoformat(),'quality_flag':'identity_verified:'+item['symbol']}
        point['revision_hash']=checksum({k:v for k,v in point.items() if k not in ('retrieved_at','available_at')})
        result.append(point)
    if not result:raise ValueError('No valid completed sessions; stored history retained')
    return result,rejected

def series_record(item):
    return {'id':item['id'],'name':item['label']+(' (calculated cross)' if item.get('cross') else ''),'provider':'Yahoo Finance','provider_series_id':' / '.join(p[0] for p in item['cross']) if item.get('cross') else item['symbol'],
            'category':'commodity' if item['category']=='commodity' else 'market','geography':'global',
            'currency':item['currency'],'unit':item['unit'],'frequency':'business_daily',
            'measurement_kind':'price' if item['kind']!='INDEX' else 'index_level',
            'source_url':'https://finance.yahoo.com/quote/'+quote(item['cross'][0][0] if item.get('cross') else item['symbol'],safe='')+'/history/',
            'storage_permission':'user_attested_import','training_permission':'unverified'}

def fx_snapshot(cloud):
    rates=[]
    for item in catalogue():
        if item['category']!='currency':continue
        rows=cloud.request('current_economic_observations?'+urlencode({'owner_id':'eq.'+cloud.owner,'series_id':'eq.'+item['id'],
            'quality_flag':'in.(identity_verified:'+item['symbol']+',derived_cross:'+item['symbol']+')','select':'observation_date,value,retrieved_at','order':'observation_date.desc','limit':2}))
        current=rows[0] if rows else None;previous=rows[1] if len(rows)>1 else None
        value=finite(current['value']) if current else None;base=finite(previous['value']) if previous else None
        rates.append({'symbol':item['symbol'],'label':item['label'],'base':item['base'],'quote':'IDR','value':value,
            'date':current['observation_date'] if current else None,'retrieved_at':current['retrieved_at'] if current else None,
            'change_percent':100*(value/base-1) if value is not None and base else None,'unit':item['unit'],'basis':item.get('basis')})
    return {'rates':rates,'storage':'Supabase','frequency':'daily_completed_sessions'}

def cross_history(item,yf,start,end,now):
    """CNY/IDR = USD/IDR divided by USD/CNY on matching completed dates.
    Direct CNY/IDR has no usable historical coverage. This is explicitly a
    calculated cross, with no forward-fill or manufactured OHLC/volume.
    """
    histories=[]
    for symbol,currency in item['cross']:
        ticker=yf.Ticker(symbol);frame=retry_transient(lambda:ticker.history(start=start,end=end,auto_adjust=False,actions=False))
        spec={'symbol':symbol,'kind':'CURRENCY','currency':currency}
        points,_=normalize_history(spec,frame,ticker.history_metadata,now)
        histories.append({p['observation_date']:p for p in points})
    result=[]
    for day in sorted(set(histories[0])&set(histories[1])):
        numerator=histories[0][day]['value'];denominator=histories[1][day]['value']
        if denominator<=0:continue
        point={'observation_date':day,'value':numerator/denominator,'open':None,'high':None,'low':None,'adjusted_close':None,
            'volume':None,'published_at':None,'available_at':now.isoformat(),'retrieved_at':now.isoformat(),'quality_flag':'derived_cross:'+item['symbol']}
        point['revision_hash']=checksum({k:v for k,v in point.items() if k not in ('retrieved_at','available_at')});result.append(point)
    if not result:raise ValueError('No matching completed FX dates for calculated cross')
    return result,0

def sync_market_history(cloud=None,symbols=None,force=False):
    import yfinance as yf
    cloud=cloud or SupabaseStore();results=[];now=datetime.now(timezone.utc)
    items=[instrument(s) for s in symbols] if symbols else catalogue()
    for item in items:
        run=str(uuid.uuid4());started=datetime.now(timezone.utc).isoformat()
        try:
            last=cloud.latest_date(item['id'])
            # Yesterday's row is not proof that today's newly completed session
            # has been collected. Always refresh a small overlap, including
            # source revisions; the database revision hash deduplicates it.
            start=(datetime.fromisoformat(last).date()-timedelta(days=8)).isoformat() if last and not force else (now.date()-timedelta(days=365*5+10)).isoformat()
            end=(now.date()+timedelta(days=1)).isoformat()
            if item.get('cross'):points,rejected=cross_history(item,yf,start,end,now)
            else:
                ticker=yf.Ticker(item['symbol'])
                frame=retry_transient(lambda:ticker.history(start=start,end=end,auto_adjust=False,actions=False))
                if frame is None or frame.empty:raise ValueError('Source returned no history')
                points,rejected=normalize_history(item,frame,ticker.history_metadata,now)
            prior={p['observation_date']:p for p in cloud.history(item['id'])} if last else {}
            def equal(a,b):return a is None and b is None or a is not None and b is not None and abs(float(a)-float(b))<=1e-8
            for point in points:
                current=prior.get(point['observation_date'])
                if not current:continue
                same=all(equal(current.get(k),point.get(k)) for k in ('value','open','high','low','volume','adjusted_close')) and current.get('quality_flag')==point['quality_flag']
                # A vendor may revise A -> B -> A. Reusing A's original hash
                # would ignore the correction and leave B as the current view.
                # Chain changed revisions; reuse the CURRENT hash for no change.
                point['revision_hash']=current['revision_hash'] if same else checksum({'observation':point['revision_hash'],'supersedes':current['revision_hash']})
            for offset in range(0,len(points),500):retry_transient(lambda:cloud.ingest(series_record(item),points[offset:offset+500],str(uuid.uuid4())))
            stored={p['observation_date']:p for p in cloud.history(item['id'])}
            if any(p['observation_date'] not in stored or any(finite(stored[p['observation_date']].get(k))!=p.get(k) for k in ('value','open','high','low','volume','adjusted_close')) for p in points):
                # PostgreSQL stores 10 decimals; compare within that explicit precision.
                if any(p['observation_date'] not in stored or any(not equal(stored[p['observation_date']].get(k),p.get(k)) for k in ('value','open','high','low','volume','adjusted_close')) for p in points):raise CloudUnavailable('Market OHLCV write verification mismatch')
            results.append({'symbol':item['symbol'],'status':'success','database_verified':True,'rows':len(stored),'received':len(points),'rejected':rejected,'last_date':max(stored)})
        except Exception as error:
            status=access_status(error)
            cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':run,'series_id':item['id'],'started_at':started,
                'finished_at':datetime.now(timezone.utc).isoformat(),'status':'failed','inserted_rows':0,'duplicate_rows':0,
                'error_code':('access_restricted:'+str(status)) if status in (401,403,429) else type(error).__name__+': existing data retained'}])
            results.append({'symbol':item['symbol'],'status':'failed','http_status':status,'error':str(error) if isinstance(error,(ValueError,CloudUnavailable)) else type(error).__name__})
            if status==429:break
        time.sleep(.4)
    CACHE.mkdir(parents=True,exist_ok=True);(CACHE/'history-sync.json').write_text(json.dumps({'generated_at':now.isoformat(),'results':results}),encoding='utf8')
    return {'status':'partial' if any(r['status']=='failed' for r in results) else 'success','results':results}

def market_history(cloud,symbol):
    if symbol and symbol.endswith('.JK'):
        from .idx_eod import EodStore,enabled_tickers
        store=EodStore()
        if symbol not in enabled_tickers(store):raise ValueError('Ticker is not in the active watchlist')
        rows=store.prices(symbol,'2021-01-01',datetime.now(timezone.utc).date().isoformat())
        points=[{'date':r['trade_date'],'value':float(r['close']),'open':finite(r.get('open')),'adjusted_close':finite(r.get('adjusted_close')),'volume':finite(r.get('volume')),'retrieved_at':r['fetched_at']} for r in rows]
        return {'instrument':{'id':symbol,'label':symbol,'symbol':symbol,'unit':'IDR/share','kind':'EQUITY','source_url':'https://finance.yahoo.com/quote/'+symbol+'/history/'},'rows':points,'identity_verified':bool(points),'storage':'Supabase','status':'available' if points else 'unavailable'}
    item=instrument(symbol);rows=cloud.history(item['id']);valid=[]
    for row in rows:
        allowed={'identity_verified:'+symbol}
        if item.get('cross'):allowed.add('derived_cross:'+symbol)
        if row['quality_flag'] not in allowed:continue
        p={k:finite(row.get(k)) for k in ('value','open','high','low','adjusted_close','volume')}
        if p['value'] is None:continue
        valid.append({**p,'date':row['observation_date'],'retrieved_at':row['retrieved_at']})
    return {'instrument':{**item,'source_url':series_record(item)['source_url']},'rows':valid,
            'storage':'Supabase','identity_verified':bool(valid),'status':'available' if valid else 'unavailable'}

UNIT_LABEL={'troy_ounce':'t.oz','barrel':'Bbl','MMBtu':'MMBtu','gallon':'Gal','metric_ton':'T','short_ton':'short ton','hundredweight':'cwt','bushel':'Bu','lb':'Lbs','board_feet':'board feet'}

def normalize_commodity(row,now):
    slug=row.get('value');currency=row.get('currency_unit');unit=row.get('unit');price=finite(row.get('price'));updated=finite(row.get('updated'))
    if not slug or not slug.replace('_','').isalnum() or currency not in ('USD','USX','EUR','GBP','CNY','MYR','CAD','AUD','BRL','NOK') or unit not in UNIT_LABEL or price is None or price<=0 or updated is None:
        raise ValueError('Invalid commodity metadata/value')
    stamp=datetime.fromtimestamp(updated,timezone.utc)
    if stamp>now+timedelta(minutes=5):raise ValueError('Future commodity update')
    change=finite(row.get('change_24h'));previous=price-change if change is not None else None
    return {**row,'id':'ninjas_'+slug,'price':price,'change_percent':100*change/previous if previous and previous>0 else None,
            'unit_label':('USd' if currency=='USX' else currency)+'/'+UNIT_LABEL[unit],
            'source_updated_at':stamp.isoformat(),'observation_date':stamp.date().isoformat(),
            'collected_at':now.isoformat(),'basis':'rolling_futures','date_basis':'source_update_not_certified_trade_date'}

def sync_commodities(cloud=None):
    cloud=cloud or SupabaseStore();key=os.environ.get('API_NINJAS_KEY');now=datetime.now(timezone.utc)
    if not key:return {'status':'not_configured','rows':0}
    request=Request('https://api.api-ninjas.com/v1/commoditysnapshot',headers={'X-Api-Key':key})
    try:
        with retry_transient(lambda:secure_open(request,timeout=25)) as response:raw=json.loads(response.read(1024*1024))
        if not isinstance(raw,list):raise ValueError('Unexpected commodity response')
        parsed=[normalize_commodity(row,now) for row in raw];seen=set()
        for q in parsed:
            if q['id'] in seen:raise ValueError('Duplicate commodity identity')
            seen.add(q['id'])
            meta={'id':q['id'],'name':q['name'],'provider':'API Ninjas','provider_series_id':q['value'],'category':'commodity',
                  'geography':'global','currency':q['currency_unit'],'unit':q['unit_label'],'frequency':'business_daily','measurement_kind':'price',
                  'source_url':'https://api-ninjas.com/api/commodityprice','storage_permission':'user_attested_import','training_permission':'unverified'}
            point={'observation_date':q['observation_date'],'value':q['price'],'published_at':None,'available_at':now.isoformat(),'retrieved_at':now.isoformat(),
                   'quality_flag':'api_ninjas_source_update_not_certified_session'}
            point['revision_hash']=checksum({'date':point['observation_date'],'price':q['price'],'unit':q['unit_label']})
            cloud.ingest(meta,[point],str(uuid.uuid4()))
        stored=read(cloud,'latest_economic_observations?'+urlencode({'owner_id':'eq.'+cloud.owner,'series_id':'in.('+','.join(seen)+')','select':'series_id,value,observation_date'}))
        checked={r['series_id']:r for r in stored}
        if any(q['id'] not in checked or abs(float(checked[q['id']]['value'])-q['price'])>1e-8 or checked[q['id']]['observation_date']!=q['observation_date'] for q in parsed):raise CloudUnavailable('Commodity readback mismatch')
        payload={'status':'success','database_verified':True,'generated_at':now.isoformat(),'quotes':parsed}
        CACHE.mkdir(parents=True,exist_ok=True);(CACHE/'commodities.json').write_text(json.dumps(payload,allow_nan=False),encoding='utf8')
        # Full source metadata, not a secret, is retained with a verified context snapshot.
        cloud.request('sector_macro_context?on_conflict=owner_id,snapshot_id',[{'owner_id':cloud.owner,'snapshot_id':checksum(payload),'generated_at':now.isoformat(),
            'payload':{'items':[],'kind':'commodity_snapshot','commodities':payload}}],prefer='resolution=ignore-duplicates,return=minimal')
        return {'status':'success','database_verified':True,'rows':len(parsed)}
    except Exception as error:
        cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':str(uuid.uuid4()),'series_id':'commodities.ninjas','started_at':now.isoformat(),
            'finished_at':datetime.now(timezone.utc).isoformat(),'status':'failed','inserted_rows':0,'duplicate_rows':0,
            'error_code':'commodity_snapshot_failed:'+str(access_status(error) or type(error).__name__)}])
        raise

def commodity_snapshot(cloud):
    rows=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'payload->>kind':'eq.commodity_snapshot','select':'payload','order':'generated_at.desc','limit':1}))
    return rows[0]['payload']['commodities'] if rows else {'status':'unavailable','database_verified':False,'quotes':[]}
