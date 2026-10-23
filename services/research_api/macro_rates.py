"""Dated official yields / dollar observations; no invented historical SBN curve."""
import csv,io,json,re,html,uuid
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from urllib.request import Request
from .cloud import SupabaseStore,CloudUnavailable
from .network import secure_open
from .providers import retry_transient,finite
from .market_data import checksum
from .market_news import read
from .rights import ROOT

ADB='https://asianbondsonline.adb.org/indonesia/'
FRED={'ust2':('US Treasury 2Y','DGS2','%'),'ust10':('US Treasury 10Y','DGS10','%'),
      'dollar_broad':('US broad dollar index','DTWEXBGS','index Jan 2006=100'),
      'fed':('Fed target upper','DFEDTARU','%'),'fed_lower':('Fed target lower','DFEDTARL','%')}

def get(url):
    def fetch():
        with secure_open(Request(url,headers={'User-Agent':'WangResearch/0.5 public macro data'}),timeout=25) as response:
            body=response.read(2_000_001)
            if len(body)>2_000_000:raise ValueError('Macro response size limit')
            return body.decode('utf-8-sig')
    return retry_transient(fetch)

def parse_adb(body,today):
    stamp=re.search(r'Close of\s*(?:<[^>]+>\s*)*([A-Za-z]+\s+\d{1,2},\s+\d{4})',body,re.I)
    if not stamp:raise ValueError('ADB observation date absent; refusing retrieval-date substitution')
    day=datetime.strptime(stamp[1],'%B %d, %Y').date()
    if day>today:raise ValueError('Future SBN observation')
    table=body[body.index('Govt. Bond Yields'):];table=table[:table.index('Currencies')]
    rows={}
    for tenor in (2,5,10):
        match=re.search(r'<td[^>]*>\s*'+str(tenor)+r' Year\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>',table,re.I)
        value=finite(match[1]) if match else None
        if value is None or not 0<value<50:raise ValueError('ADB tenor / yield format changed')
        rows['sbn'+str(tenor)]=(day.isoformat(),value)
    return rows

def parse_fred(body,provider,today):
    rows=list(csv.DictReader(io.StringIO(body)))
    if not rows or provider not in rows[0]:raise ValueError('Unexpected FRED columns')
    key='observation_date' if 'observation_date' in rows[0] else 'DATE'
    points=[];seen=set()
    for row in rows:
        day=datetime.strptime(row[key],'%Y-%m-%d').date();value=finite(row[provider])
        if day.isoformat() in seen:raise ValueError('Duplicate official observation date')
        seen.add(day.isoformat())
        if day<=today and value is not None:points.append((day.isoformat(),value))
    if not points:raise ValueError('No numeric official observations')
    return points

def meta(key,label,unit,url,provider):
    return {'id':'macro_daily_'+key,'name':label,'provider':provider,'provider_series_id':key,
        'category':'macro','geography':'Indonesia' if key.startswith('sbn') else 'US','currency':None,
        'unit':unit,'frequency':'business_daily','measurement_kind':'rate' if unit=='%' else 'index_level',
        'source_url':url,'storage_permission':'user_attested_import','training_permission':'unverified'}

def persist(cloud,key,label,unit,url,provider,values,now):
    series=meta(key,label,unit,url,provider);prior={p['observation_date']:p for p in cloud.history(series['id'])};points=[]
    for day,value in values:
        old=prior.get(day)
        revision=old['revision_hash'] if old and abs(float(old['value'])-value)<1e-8 else checksum({'day':day,'value':value,'supersedes':old.get('revision_hash') if old else None})
        points.append({'observation_date':day,'value':value,'published_at':None,'available_at':now.isoformat(),
            'retrieved_at':now.isoformat(),'revision_hash':revision,'quality_flag':'dated_public_source'})
    for start in range(0,len(points),500):cloud.ingest(series,points[start:start+500],str(uuid.uuid4()))
    checked={p['observation_date']:p for p in cloud.history(series['id'])}
    if any(p['observation_date'] not in checked or abs(float(checked[p['observation_date']]['value'])-p['value'])>1e-8 for p in points):raise CloudUnavailable('Official macro write verification failed')
    return {'id':key,'status':'success','database_verified':True,'last_date':max(checked),'rows':len(checked)}

def refresh_rates(cloud=None):
    cloud=cloud or SupabaseStore();now=datetime.now(timezone.utc);results=[]
    for key,(label,code,unit) in FRED.items():
        try:
            last=cloud.latest_date('macro_daily_'+key)
            start=(datetime.fromisoformat(last).date()-timedelta(days=10)).isoformat() if last else (now.date()-timedelta(days=365*5+10)).isoformat()
            values=parse_fred(get('https://fred.stlouisfed.org/graph/fredgraph.csv?'+urlencode({'id':code,'cosd':start})),code,now.date())
            results.append(persist(cloud,key,label,unit,'https://fred.stlouisfed.org/series/'+code,'FRED / Federal Reserve',values,now))
        except Exception as error:results.append({'id':key,'status':'failed','error_type':type(error).__name__})
    try:
        values=parse_adb(get(ADB),now.date())
        for key,value in values.items():results.append(persist(cloud,key,'SBN Indonesia '+key[3:]+'Y','%',ADB,'AsianBondsOnline / ADB',[value],now))
    except Exception as error:results.append({'id':'sbn','status':'failed','error_type':type(error).__name__})
    for r in results:
        cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':str(uuid.uuid4()),'series_id':'macro_daily_'+r['id'],
            'started_at':now.isoformat(),'finished_at':datetime.now(timezone.utc).isoformat(),'status':r['status'],
            'inserted_rows':0,'duplicate_rows':0,'error_code':r.get('error_type')}])
    # Existing official dataset is retained. The cloud copy is authoritative on ephemeral CI.
    data=macro_dataset(cloud)
    path=ROOT/'public/data/macro-history.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8')
    from .sector_trends import save_macro_context
    save_macro_context(cloud)
    return {'results':results,'status':'success' if all(r['status']=='success' for r in results) else 'partial','database_verified':any(r.get('database_verified') for r in results)}

def macro_dataset(cloud):
    contexts=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'payload->>kind':'is.null','select':'payload','order':'generated_at.desc','limit':1}))
    path=ROOT/'public/data/macro-history.json'
    data=contexts[0]['payload'].get('intelligence_dataset',{}) if contexts else {}
    if path.exists():
        local=json.loads(path.read_text(encoding='utf8'))
        from .sector_intelligence import merge_macro_dataset
        merged=merge_macro_dataset(local,data)
        # A stale local preview must not replace a later cloud revision.
        old={(p['seriesId'],p['date']):p for p in data.get('observations',[])}
        merged['observations']=[old.get((p['seriesId'],p['date']),p) if old.get((p['seriesId'],p['date']),{}).get('retrievedAt','')>p.get('retrievedAt','') else p for p in merged['observations']]
        data=merged
    data=json.loads(json.dumps(data));data.setdefault('schemaVersion',1);data.setdefault('series',[]);data.setdefault('observations',[]);data.setdefault('sources',[]);data.setdefault('failures',[])
    specs=[(k,l,u,'https://fred.stlouisfed.org/series/'+c,'FRED / Federal Reserve','macro_daily_'+k) for k,(l,c,u) in FRED.items()]
    specs += [('sbn'+str(n),'SBN Indonesia '+str(n)+'Y','%',ADB,'AsianBondsOnline / ADB','macro_daily_sbn'+str(n)) for n in (2,5,10)]
    specs += [('dxy','US Dollar Index (DXY)','index','https://finance.yahoo.com/quote/DX-Y.NYB/history/','Market data','market_dxy')]
    specs += [('usdidr','USD/IDR daily close','IDR / USD','https://finance.yahoo.com/quote/IDR=X/history/','Market data','fx_usd_idr')]
    for key,label,unit,url,provider,sid in specs:
        rows=cloud.history(sid)
        if not rows:continue
        data['series']=[s for s in data['series'] if s['id']!=key]
        data['observations']=[p for p in data['observations'] if p['seriesId']!=key]
        description=('Government local-currency benchmark yield; tenor '+key[3:]+' years. Daily collection starts at first verified observation; no synthetic backfill.' if key.startswith('sbn') else 'Dated official observations; publication / release vintage unknown. Broad dollar index is distinct from DXY.' if key!='dxy' else 'ICE US dollar index; distinct from the trade-weighted broad USD index.')
        data['series'].append({'id':key,'label':label,'unit':unit,'frequency':'business-daily','source':provider,'sourceUrl':url,'description':description,'coverageStart':rows[0]['observation_date'],'coverageEnd':rows[-1]['observation_date'],'retrievedAt':max(p['retrieved_at'] for p in rows),'publicationKnown':False})
        data['observations'] += [{'seriesId':key,'date':p['observation_date'],'value':float(p['value']),'retrievedAt':p['retrieved_at'],'publishedAt':p.get('published_at'),'availableAt':p.get('available_at'),'sourceUrl':url} for p in rows]
    data.update(asOf=datetime.now(timezone.utc).date().isoformat(),generatedAt=max([p.get('retrievedAt','') for p in data['observations']]+[data.get('generatedAt','')]))
    return data
