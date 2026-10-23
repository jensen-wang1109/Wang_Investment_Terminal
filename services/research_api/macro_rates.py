"""Dated official yields / dollar observations; no invented historical SBN curve."""
import csv,io,json,re,html,uuid
import xml.etree.ElementTree as ET
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
H10='https://www.federalreserve.gov/releases/h10/current/'
TREASURY='https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
FED_POLICY='https://www.federalreserve.gov/monetarypolicy/openmarket.htm'
FRED={'ust2':('US Treasury 2Y','DGS2','%'),'ust10':('US Treasury 10Y','DGS10','%'),
      'dollar_broad':('US broad dollar index','DTWEXBGS','index Jan 2006=100'),
      'fed':('Fed target upper','DFEDTARU','%'),'fed_lower':('Fed target lower','DFEDTARL','%')}

def get(url):
    def fetch():
        with secure_open(Request(url,headers={'User-Agent':'WangResearch/0.5 public macro data'}),timeout=12) as response:
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

def parse_treasury(body,today):
    root=ET.fromstring(body);out={'ust2':[],'ust10':[]};seen=set()
    for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
        fields={c.tag.split('}')[-1]:c.text for c in entry.iter()}
        day=(fields.get('NEW_DATE') or '')[:10]
        if not day:raise ValueError('Treasury observation date absent')
        stamp=datetime.strptime(day,'%Y-%m-%d').date()
        if day in seen:raise ValueError('Duplicate Treasury date')
        seen.add(day)
        if stamp>today:continue
        for key,field in [('ust2','BC_2YEAR'),('ust10','BC_10YEAR')]:
            value=finite(fields.get(field))
            if value is not None and 0<=value<50:out[key].append((day,value))
    if not all(out.values()):raise ValueError('Treasury tenor missing')
    return out

def parse_h10(body,today):
    release=re.search(r'Release Date:\s*([A-Za-z]+ \d{1,2}, \d{4})',body)
    if not release:raise ValueError('H10 release date absent')
    stamp=datetime.strptime(release[1],'%B %d, %Y').date()
    if stamp>today:raise ValueError('Future H10 release')
    headings=dict(re.findall(r'<th id="(a[3-7])">\s*([A-Za-z]+\.\s+\d{1,2})\s*</th>',body))
    match=re.search(r'<th[^>]*>1\) BROAD\s*</th>(.*?)</tr>',body,re.S)
    if not match or len(headings)!=5:raise ValueError('H10 broad-index structure changed')
    out=[]
    for column,text in re.findall(r'<td headers="(a[3-7]) a1 r1">\s*([^<]+)</td>',match[1]):
        value=finite(text.strip())
        if value is None:continue
        day=datetime.strptime(headings[column].replace('.','')+' '+str(stamp.year),'%b %d %Y').date()
        if day>stamp:day=day.replace(year=day.year-1)
        if value<=0:raise ValueError('Nonpositive broad dollar index')
        out.append((day.isoformat(),value))
    if not out:raise ValueError('No numeric H10 broad-index observations')
    return out

def parse_policy(body,today):
    values=[]
    for year,table in re.findall(r'<h4>\s*(20\d{2})\s*</h4>.*?<table[^>]*>(.*?)</table>',body,re.S):
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>',table,re.S):
            cells=[' '.join(html.unescape(re.sub('<[^>]+>',' ',c)).split()) for c in re.findall(r'<td[^>]*>(.*?)</td>',row,re.S)]
            if len(cells)!=4:continue
            try:day=datetime.strptime(cells[0]+' '+year,'%B %d %Y').date()
            except ValueError:continue
            match=re.fullmatch(r'([\d.]+)\s*-\s*([\d.]+)',cells[3])
            if day<=today and match:
                lower,upper=map(float,match.groups())
                if not 0<=lower<upper<50:raise ValueError('Invalid Fed target range')
                values.append((day.isoformat(),lower,upper))
    if not values:raise ValueError('Fed policy changes table unavailable')
    return max(values,key=lambda r:r[0])

def meta(key,label,unit,url,provider):
    prefix={'US Treasury':'macro_treasury_','Federal Reserve H10':'macro_fedh10_','Federal Reserve policy changes':'macro_fedpolicy_'}.get(provider,'macro_daily_')
    return {'id':prefix+key,'name':label,'provider':provider,'provider_series_id':key,
        'category':'macro','geography':'Indonesia' if key.startswith('sbn') else 'US','currency':None,
        'unit':unit,'frequency':'business_daily','measurement_kind':'rate' if unit=='%' else 'index_level',
        'source_url':url,'storage_permission':'user_attested_import','training_permission':'unverified'}

def persist(cloud,key,label,unit,url,provider,values,now):
    series=meta(key,label,unit,url,provider);prior={p['observation_date']:p for p in cloud.history(series['id'])};points=[]
    for day,value in values:
        old=prior.get(day)
        quality='dated_public_source:'+('treasury' if provider=='US Treasury' else 'fed_h10' if provider=='Federal Reserve H10' else 'fed_policy' if provider=='Federal Reserve policy changes' else 'adb' if key.startswith('sbn') else 'fred')
        revision=old['revision_hash'] if old and abs(float(old['value'])-value)<1e-8 and old.get('quality_flag')==quality else checksum({'day':day,'value':value,'source':quality,'supersedes':old.get('revision_hash') if old else None})
        points.append({'observation_date':day,'value':value,'published_at':None,'available_at':now.isoformat(),
            'retrieved_at':now.isoformat(),'revision_hash':revision,'quality_flag':quality})
    for start in range(0,len(points),500):cloud.ingest(series,points[start:start+500],str(uuid.uuid4()))
    checked={p['observation_date']:p for p in cloud.history(series['id'])}
    if any(p['observation_date'] not in checked or abs(float(checked[p['observation_date']]['value'])-p['value'])>1e-8 for p in points):raise CloudUnavailable('Official macro write verification failed')
    return {'id':key,'status':'success','database_verified':True,'last_date':max(checked),'rows':len(checked)}

def refresh_rates(cloud=None):
    cloud=cloud or SupabaseStore();now=datetime.now(timezone.utc);results=[];completed=set()
    # Independent primary publishers avoid relying on the FRED host from CI.
    try:
        url=TREASURY+'?'+urlencode({'data':'daily_treasury_yield_curve','field_tdr_date_value':now.year})
        values=parse_treasury(get(url),now.date())
        for key,points in values.items():
            results.append(persist(cloud,key,FRED[key][0],'%',url,'US Treasury',points[-10:],now));completed.add(key)
    except Exception as error:results.append({'id':'treasury_primary','status':'failed','error_type':type(error).__name__})
    try:
        values=parse_h10(get(H10),now.date())
        results.append(persist(cloud,'dollar_broad',FRED['dollar_broad'][0],FRED['dollar_broad'][2],H10,'Federal Reserve H10',values,now));completed.add('dollar_broad')
    except Exception as error:results.append({'id':'dollar_primary','status':'failed','error_type':type(error).__name__})
    try:
        day,lower,upper=parse_policy(get(FED_POLICY),now.date())
        for key,value in [('fed_lower',lower),('fed',upper)]:
            # Store the actual policy-change date. Never manufacture a row for
            # today merely because the unchanged target was checked today.
            results.append(persist(cloud,key,FRED[key][0],'%',FED_POLICY,'Federal Reserve policy changes',[(day,value)],now));completed.add(key)
    except Exception as error:results.append({'id':'policy_primary','status':'failed','error_type':type(error).__name__})
    fred_circuit=False
    for key,(label,code,unit) in FRED.items():
        if key in completed:continue
        if fred_circuit:
            results.append({'id':key,'status':'retained','reason':'FRED transport circuit open; prior dated observations retained'});continue
        try:
            last=cloud.latest_date('macro_daily_'+key)
            start=(datetime.fromisoformat(last).date()-timedelta(days=10)).isoformat() if last else (now.date()-timedelta(days=365*5+10)).isoformat()
            values=parse_fred(get('https://fred.stlouisfed.org/graph/fredgraph.csv?'+urlencode({'id':code,'cosd':start})),code,now.date())
            results.append(persist(cloud,key,label,unit,'https://fred.stlouisfed.org/series/'+code,'FRED / Federal Reserve',values,now))
        except Exception as error:
            results.append({'id':key,'status':'failed','error_type':type(error).__name__})
            from urllib.error import URLError,HTTPError
            if isinstance(error,(TimeoutError,URLError)) and not isinstance(error,HTTPError):fred_circuit=True
    try:
        values=parse_adb(get(ADB),now.date())
        for key,value in values.items():results.append(persist(cloud,key,'SBN Indonesia '+key[3:]+'Y','%',ADB,'AsianBondsOnline / ADB',[value],now))
    except Exception as error:results.append({'id':'sbn','status':'failed','error_type':type(error).__name__})
    for r in results:
        cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':str(uuid.uuid4()),'series_id':'macro_daily_'+r['id'],
            'started_at':now.isoformat(),'finished_at':datetime.now(timezone.utc).isoformat(),'status':'failed' if r['status']=='retained' else r['status'],
            'inserted_rows':0,'duplicate_rows':0,'error_code':r.get('error_type') or r.get('reason')}])
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
        # Keep each publisher in its own immutable series. Merge only the
        # displayed economic measure, with per-observation source attribution.
        for point in rows:point['_source_url']=url;point['_provider']=provider
        primary_sid='macro_treasury_'+key if key in ('ust2','ust10') else 'macro_fedh10_'+key if key=='dollar_broad' else 'macro_fedpolicy_'+key if key in ('fed','fed_lower') else None
        if primary_sid:
            alternate=cloud.history(primary_sid)
            alt_url=TREASURY if key in ('ust2','ust10') else H10 if key=='dollar_broad' else FED_POLICY
            alt_provider='US Treasury' if key in ('ust2','ust10') else 'Federal Reserve H10 · daily observations, weekly publication' if key=='dollar_broad' else 'Federal Reserve policy changes'
            merged={p['observation_date']:p for p in rows}
            for point in alternate:
                point['_source_url']=alt_url;point['_provider']=alt_provider
                old=merged.get(point['observation_date'])
                if old and abs(float(old['value'])-float(point['value']))>1e-6:
                    data['failures'].append({'provider':alt_provider,'seriesId':key,'error':'Primary / FRED source conflict; both originals retained, primary displayed. Review required.'})
                    point['_source_conflict']=True
                merged[point['observation_date']]=point
            rows=[merged[d] for d in sorted(merged)]
        if not rows:continue
        url=rows[-1]['_source_url'];provider=rows[-1]['_provider']
        data['series']=[s for s in data['series'] if s['id']!=key]
        data['observations']=[p for p in data['observations'] if p['seriesId']!=key]
        description=('Government local-currency benchmark yield; tenor '+key[3:]+' years. Daily collection starts at first verified observation; no synthetic backfill.' if key.startswith('sbn') else 'Dated official observations; publication / release vintage unknown. Broad dollar index is distinct from DXY.' if key!='dxy' else 'ICE US dollar index; distinct from the trade-weighted broad USD index.')
        if key=='dollar_broad':description+=' H10 daily observations are published weekly; daily collection does not imply same-day publication.'
        data['series'].append({'id':key,'label':label,'unit':unit,'frequency':'daily' if key in ('fed','fed_lower') else 'business-daily','publicationCadence':'weekly' if key=='dollar_broad' else None,'source':provider,'sourceUrl':url,'description':description,'coverageStart':rows[0]['observation_date'],'coverageEnd':rows[-1]['observation_date'],'retrievedAt':max(p['retrieved_at'] for p in rows),'publicationKnown':False})
        if not rows[-1].get('_source_conflict'):
            data['failures']=[f for f in data['failures'] if f.get('seriesId')!=key or 'conflict' in f.get('error','').lower()]
        data['observations'] += [{'seriesId':key,'date':p['observation_date'],'value':float(p['value']),'retrievedAt':p['retrieved_at'],'publishedAt':p.get('published_at'),'availableAt':p.get('available_at'),'sourceUrl':p['_source_url'],'sourceConflict':p.get('_source_conflict',False)} for p in rows]
    data.update(asOf=datetime.now(timezone.utc).date().isoformat(),generatedAt=max([p.get('retrievedAt','') for p in data['observations']]+[data.get('generatedAt','')]))
    data['failures']=list({json.dumps(f,sort_keys=True):f for f in data['failures']}.values())
    return data
