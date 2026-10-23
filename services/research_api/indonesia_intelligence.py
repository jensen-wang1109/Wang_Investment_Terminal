"""Indonesia-first deterministic state, event materiality and shared industry impacts.

Every conclusion is tied to dated features. No return model is trained here.
This module has no network, DB writes, or dependency on company fundamentals.
"""
import copy,hashlib,json,math,re,statistics
from datetime import datetime,timedelta,timezone,date
from urllib.parse import urlparse
from .rights import ROOT

VERSION='indonesia-first-v2.0'
JAKARTA=timezone(timedelta(hours=7))
CHANNELS=['growth_trade','rupiah_flows','inflation_rates','ihsg_risk_appetite','industry_cost_earnings']

def settings():return json.loads((ROOT/'config/intelligence-v2.json').read_text(encoding='utf8'))
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def numeric(v):return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)

def market_features(rows,now,expected=None):
    """Unadjusted observable closes; no imputation across absent dates."""
    points={};bad=set()
    for row in rows:
        day=row.get('date',row.get('trade_date'));value=row.get('value',row.get('close'))
        stamp=row.get('retrieved_at',row.get('fetched_at'))
        if not day or day>now.astimezone(JAKARTA).date().isoformat() or not numeric(value) or value<=0:continue
        if stamp and datetime.fromisoformat(stamp.replace('Z','+00:00'))>now:continue
        if day in points:bad.add(day)
        points[day]={'date':day,'value':float(value),'volume':row.get('volume')}
    bars=sorted((p for day,p in points.items() if day not in bad),key=lambda p:p['date'])
    if not bars:return {'status':'missing','last_date':None,'returns':{},'ma':{},'volatility':None,'volume_ratio':None,'observations':0,'direction':'Insufficient Evidence'}
    last=bars[-1];values=[p['value'] for p in bars];age=(now.astimezone(JAKARTA).date()-date.fromisoformat(last['date'])).days
    stale=last['date']<expected if expected else age>settings()['market_stale_calendar_days']
    # Returns require >90% weekday coverage; exchange holidays can reduce this
    # denominator slightly. The IDX collector validates the official calendar.
    returns={}
    for n in (1,5,20,21,63,126):
        if len(bars)>n:
            span=(date.fromisoformat(last['date'])-date.fromisoformat(bars[-n-1]['date'])).days
            if span<=n*2+7:returns[str(n)]=values[-1]/values[-n-1]-1
    ma={str(n):statistics.mean(values[-n:]) for n in (20,50,200) if len(values)>=n}
    changes=[values[i]/values[i-1]-1 for i in range(max(1,len(values)-20),len(values)) if (date.fromisoformat(bars[i]['date'])-date.fromisoformat(bars[i-1]['date'])).days<=4]
    vol=statistics.stdev(changes)*math.sqrt(252) if len(changes)>=15 else None
    volumes=[p['volume'] for p in bars[-21:-1] if numeric(p['volume']) and p['volume']>0]
    volume_ratio=last['volume']/statistics.mean(volumes) if numeric(last['volume']) and len(volumes)>=15 else None
    r5=returns.get('5');r20=returns.get('20')
    direction='Insufficient Evidence' if stale or r5 is None or r20 is None or '20' not in ma else 'Improving' if r5>0 and r20>0 and last['value']>ma['20'] else 'Deteriorating' if r5<0 and r20<0 and last['value']<ma['20'] else 'Stable / Mixed'
    return {'status':'stale' if stale else 'available','last_date':last['date'],'value':last['value'],'observations':len(bars),'returns':returns,'ma':ma,'volatility':vol,'volume_ratio':volume_ratio,'direction':direction,'last_5_dates':[p['date'] for p in bars[-5:]]}

def event_metadata(context,previous,now):
    """Conservative event clustering: same driver/state/day is ONE event.

    This may merge distinct announcements; it deliberately cannot manufacture
    independent confirmations from repeated media coverage.
    """
    prior={e['event_id']:e for e in (previous or {}).get('events',[])};events={}
    for signal in context.get('signals',[]):
        topic=signal['id'];fact=signal.get('fact')
        candidates=signal.get('evidence',[])
        if fact:candidates=[{'title':fact.get('title',signal['title']),'url':fact['source_url'],'published_at':fact['published_date']+'T00:00:00+00:00','primary_fact':fact}]+candidates
        for a in candidates:
            stamp=a.get('published_at')
            if not stamp or datetime.fromisoformat(stamp.replace('Z','+00:00'))>now:continue
            title=a.get('title','');low=title.casefold();primary=a.get('primary_fact')
            host=(urlparse(a.get('url','')).hostname or '').lower()
            official=bool(primary and primary.get('verification_status')!='needs_review')
            # An official-looking host alone does not verify the reported claim.
            proposal=bool(re.search(r'\bakan\b|rencana|usul|propos|konsultasi|berpotensi|rumor|diduga|prediksi',low))
            negated=bool(re.search(r'\b(?:belum|tidak|bantah|bukan|batal)\b',low))
            state=primary.get('event_state') if official else 'negated_or_contested' if negated else 'proposal_or_speculation' if proposal else 'reported_unverified'
            action='tightening' if re.search(r'naikkan|menaikkan|hike|suku bunga naik',low) else 'easing' if re.search(r'pangkas|turunkan|cut|pelonggaran',low) else 'disruption' if re.search(r'gangguan|krisis|perang|blokade',low) else 'increase' if re.search(r'naik|menguat|meningkat',low) else 'decrease' if re.search(r'turun|melemah|merosot',low) else 'review'
            identity=digest([topic,stamp[:10],state,action]);key=identity
            relevant=topic in ('market_access','domestic_monetary','domestic_growth','global_monetary','energy','biodiesel','commodities','ai_capex')
            numeric_confirmation=bool(signal.get('numeric_evidence'))
            quality='verified_primary' if official else 'headline_only'
            materiality='HIGH' if official and relevant else 'MODERATE' if relevant else 'LOW'
            if topic=='global_equities':materiality='LOW' # index spillover is assessed with actual IHSG/FX prices
            if key not in events:
                events[key]={'event_id':identity,'topic':topic,'event_date':stamp[:10],'state':state,'action':action,'title':title[:220],
                    'source_reliability':quality,'evidence_quality':quality,'materiality':materiality,'references':[],
                    'variables':signal.get('confirm',[]),'channels':CHANNELS if relevant else ['ihsg_risk_appetite'],
                    'exposure':'direct domestic' if topic.startswith('domestic') or topic=='market_access' else 'indirect / conditional',
                    'lag':'days to weeks for flows / FX; 1–6 months for demand / costs',
                    'direction':'conditional / offsetting; not a forecast from title',
                    'independent_confirmations':1 if official else 0,'new':identity not in prior,
                    'mechanism':signal.get('macro',''),'conditions':signal.get('confirm',[]),'invalidation':signal.get('invalidate','')}
            event=events[key]
            ref={'url':a.get('url'),'title':title[:220],'observed_at':stamp,'primary_verified':official}
            if ref['url'] and ref['url'] not in {r['url'] for r in event['references']} and len(event['references'])<3:event['references'].append(ref)
    return sorted(events.values(),key=lambda e:(e['materiality']!='HIGH',e['event_date']),reverse=False)

def stable_regime(candidate,previous,now,support,conflicts,confidence,urgent=False):
    old=previous or {};current=old.get('current');pending=old.get('candidate');count=old.get('persistence',0)
    today=now.astimezone(JAKARTA).date().isoformat();different_day=old.get('evaluated_date')!=today
    count=(count+int(different_day)) if pending==candidate else 1
    insufficient=candidate in ('Uncertain / Mixed','Insufficient Evidence')
    adopted=candidate if not current or insufficient or urgent or count>=settings()['regime_persistence_days'] else current
    return {'current':adopted,'previous':current,'candidate':candidate,'persistence':count,'evaluated_date':today,
        'materially_changed':bool(current and adopted!=current),'pending_confirmation':adopted!=candidate,
        'support':support,'conflicts':conflicts,'confidence':confidence,
        'method':'Two distinct daily observations before ordinary regime changes; missing data cannot retain an apparently confident regime.'}

def build_indonesia(context,indicators,previous,now):
    cfg=settings();previous=previous or {};by={x['id']:x for x in indicators};fresh={k:v for k,v in by.items() if not v['stale']}
    prices={p['symbol']:p for p in context.get('prices',[])}
    ihsg=copy.deepcopy(prices.get('^JKSE',{}).get('features',market_features([],now)))
    fx=copy.deepcopy(prices.get('IDR=X',{}).get('features',market_features([],now)))
    # Quarterly growth alone cannot identify the full economic cycle.
    support=[];conflicts=[]
    for key in ('gdp','inflation','bi','id_credit','id_m2','id_retail','id_industrial','id_trade','id_reserves'):
        if key in fresh:support.append({'id':key,'value':fresh[key]['value'],'date':fresh[key]['observation_date'],'trend':fresh[key]['regime'],'source_url':fresh[key]['source_url']})
    leading=[fresh[k] for k in ('id_credit','id_m2','id_retail','id_industrial') if k in fresh and fresh[k]['regime']!='insufficient']
    gdp=fresh.get('gdp');candidate='Uncertain / Mixed'
    if gdp and len(leading)>=2:
        positive=sum(x['regime']=='rising' for x in leading);negative=sum(x['regime']=='falling' for x in leading)
        if gdp['value']<0 and negative>=2:candidate='Contraction'
        elif gdp['regime']=='falling' and negative>=2:candidate='Slowdown'
        elif gdp['value']>0 and positive>=2:
            candidate='Recovery' if (previous.get('economic_regime',{}).get('current') in ('Contraction','Slowdown')) else 'Early Expansion' if gdp['regime']=='rising' else 'Mid Expansion'
            if fresh.get('inflation',{}).get('regime')=='rising' and fresh.get('bi',{}).get('regime')=='rising':candidate='Late Expansion'
    missing=[k for k in ('id_m2','id_credit','id_retail','id_industrial','id_trade','id_current_account','id_reserves','foreign_flows','official_breadth','index_concentration') if k not in fresh]
    if len(leading)<2:conflicts.append('Kredit, M2 dan indikator aktivitas belum cukup; PDB lagging saja tidak menetapkan fase siklus.')
    economy=stable_regime(candidate,previous.get('economic_regime'),now,support,conflicts,'low' if candidate=='Uncertain / Mixed' else 'moderate')
    direction=ihsg['direction'];equity='Insufficient Evidence' if direction=='Insufficient Evidence' else 'High Volatility / Risk-Off' if (ihsg.get('volatility') or 0)>.4 and direction=='Deteriorating' else 'Bullish' if direction=='Improving' else 'Bearish' if direction=='Deteriorating' else 'Neutral / Consolidating'
    risk_events=event_metadata(context,previous,now)
    drivers=[]
    for key in ('bi','inflation','ust10','dollar_broad','dxy','sbn10'):
        if key in fresh:drivers.append({'id':key,'name':fresh[key]['name'],'value':fresh[key]['value'],'trend':fresh[key]['regime'],'date':fresh[key]['observation_date'],'source_url':fresh[key]['source_url']})
    market_support=[{'id':'IHSG','return5':ihsg.get('returns',{}).get('5'),'return20':ihsg.get('returns',{}).get('20'),'date':ihsg['last_date']}]
    market_conflicts=['Arus asing, konsentrasi konstituen dan breadth resmi belum tersedia; kenaikan indeks belum membuktikan partisipasi luas.']
    fxr=fx.get('returns',{}).get('20');rupiah='Insufficient Evidence' if fx['status']!='available' or fxr is None else 'Rupiah strengthening bias' if fxr<-.005 else 'Rupiah weakening bias' if fxr>.005 else 'Neutral / Mixed'
    equity_regime=stable_regime(equity,previous.get('equity_regime'),now,market_support,market_conflicts,'low' if ihsg['status']!='available' else 'moderate',urgent=equity=='High Volatility / Risk-Off')
    if fxr and fxr>.005 and direction=='Improving':market_conflicts.append('IHSG menguat saat rupiah tertekan; arah pasar dan tekanan eksternal belum sejalan.')
    ihsg.update(outlook=direction,horizon_weeks=cfg['outlook_weeks'],macro_supported_outlook='Insufficient Evidence' if candidate=='Uncertain / Mixed' else direction,
        drivers=drivers,conflicts=market_conflicts,invalidation='Tinjau ulang jika return 5/20 sesi dan MA20 berbalik, rupiah tertekan, atau kebijakan / arus dana berubah.',
        scope='Indeks IHSG aktual. Breadth watchlist, bila tersedia, hanyalah proxy sampel; bukan breadth resmi IDX.')
    fx.update(outlook=rupiah,drivers=drivers,invalidation='Tinjau ulang jika USD/IDR berbalik terhadap MA20 atau arah dolar, yield AS dan respons BI berubah.',
        uncertainty='Arus modal, cadangan devisa dan perdagangan frekuensi terkini belum lengkap. Broad USD bukan DXY.')
    # Both views consume this exact relationship set, never independently drafted implications.
    impacts=[]
    topic_event={e['topic']:e for e in risk_events if e['materiality']!='LOW'}
    for signal in context.get('signals',[]):
        event=topic_event.get(signal['id'])
        if not event:continue
        for kind in ('beneficiaries','pressured'):
            for item in signal.get(kind,[]):
                impacts.append({'industry':item['industry'],'direction':'potential_beneficiary' if kind=='beneficiaries' else 'potential_risk',
                    'event_id':event['event_id'],'topic':signal['id'],'mechanism':signal['macro'],'condition':item['condition'],
                    'lag':'1–6 months; contract / capex delivery may be longer','exceptions':signal['invalidate'],
                    'evidence_quality':event['evidence_quality'],'relationship_version':VERSION,'eligible_recommendation':False})
    changes=[];oldprices=previous.get('observed_prices',{})
    for symbol,threshold in cfg['material_change_pct'].items():
        current=prices.get(symbol);old=oldprices.get(symbol)
        if current and old and current['observation_date']>old['date'] and old['value']>0:
            delta=(current['value']/old['value']-1)*100
            if abs(delta)>=threshold:changes.append({'title':current['name'],'previous':old,'current':{'value':current['value'],'date':current['observation_date']},'change_pct':delta,'source_url':current['source_url'],'why':'Perubahan harga memengaruhi risiko IHSG / rupiah atau biaya energi; penyebab memerlukan konfirmasi.','priority':1 if symbol=='^JKSE' else 2 if symbol=='IDR=X' else 4})
    oldmacro=previous.get('observed_macro',{})
    for key in ('bi','inflation','gdp','ust10','dollar_broad','sbn10'):
        item=fresh.get(key);old=oldmacro.get(key)
        if item and old and item['observation_date']>old['date'] and abs(item['value']-old['value'])>=(.1 if item['unit'].startswith('%') else 1):
            changes.append({'title':item['name'],'previous':old,'current':{'value':item['value'],'date':item['observation_date']},'source_url':item['source_url'],'why':'Perubahan kondisi pendanaan / ekonomi Indonesia; nilai observasi dipisahkan dari inferensi transmisi.','priority':0 if key in ('bi','inflation','gdp') else 3})
    for e in risk_events:
        if e['new'] and e['materiality']=='HIGH':changes.append({'title':e['title'],'previous':{'value':'not previously recorded','date':None},'current':{'value':e['state'],'date':e['event_date']},'source_url':e['references'][0]['url'],'why':e['mechanism'],'priority':3})
    changes=sorted(changes,key=lambda c:c['priority'])[:5]
    summary=(f"Rezim ekonomi Indonesia dinilai {economy['current']}; data PDB, inflasi dan kebijakan BI dibaca bersama, sementara cakupan kredit, likuiditas dan aktivitas belum lengkap. "
        f"Kondisi IHSG: {equity_regime['current']}, dengan arah harga {direction}; arah ini belum otomatis menjadi outlook yang dikonfirmasi makro. "
        f"Bias rupiah: {rupiah}. Perubahan yield AS, dolar, suku bunga domestik dan biaya energi ditelaah melalui dampaknya pada pendanaan, inflasi serta daya beli Indonesia. "
        "Berita yang belum terverifikasi tetap berupa skenario, termasuk usulan perubahan akses pasar. Manfaat bagi produsen dapat berlawanan dengan tekanan pada pengguna input dan IHSG secara keseluruhan. "
        "Lingkungan investasi belum dapat dinyatakan membaik secara menyeluruh tanpa konfirmasi partisipasi pasar, arus dana dan indikator domestik. Prioritaskan bukti baru, tanggal observasi dan kondisi pembatal tesis; skor riset industri bukan probabilitas return.")
    return {'version':VERSION,'economic_regime':economy,'equity_regime':equity_regime,'executive_summary':summary,
        'changes':changes,'change_message':None if changes else 'No Material Macro Change.',
        'ihsg':ihsg,'rupiah':fx,'events':risk_events,'industry_impacts':impacts,'missing_inputs':missing,
        'observed_prices':{k:{'value':v['value'],'date':v['observation_date']} for k,v in prices.items()},
        'observed_macro':{k:{'value':v['value'],'date':v['observation_date']} for k,v in fresh.items()},
        'baseline_status':'previous_daily_state_available' if previous else 'initial_baseline; changes require a prior daily observation',
        'monitor':['BI, inflasi, kredit / M2 dan aktivitas domestik','USD/IDR, dolar global, yield AS / SBN','IHSG, breadth sampel dan relative strength beberapa emiten','Keputusan primer dan realisasi kebijakan / kontrak'],
        'forecast_status':'Heuristic research framework; no validated return probabilities or exact targets.',
        'point_in_time_ready':False,'data_quality':{'domestic_indicators':len(support),'missing':len(missing),'full_idx_breadth':False}}
