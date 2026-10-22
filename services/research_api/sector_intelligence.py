"""Selective macro -> industry research. Scores are evidence coverage, never probabilities.

The graph is a falsifiable hypothesis library. Headline counts cannot establish
supply deficits, issuer revenue exposure, earnings revisions or undervaluation.
Only timestamped, reviewed assertions may fill those missing factors.
"""
import copy
import hashlib
import json
import math
import re
import statistics
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse
from .cloud import CloudUnavailable
from .market_news import read
from .news_analyzer import instant
from .feeds import approved_article
from .rights import ROOT

from .sector_rotation import WEIGHTS, LABELS, industry_features, combine_factors, macro_factor, leading_factor

VERSION = 'sector-macro-rotation-v3.1'
DEFAULTS = {'weights': WEIGHTS, 'high':80,'developing':65,'watch':50,
    'minimum_data_quality':70,'minimum_metric_weight':65,'score_change':10,
    'cooldown_hours':72,'max_industries':3,'minimum_turnover_idr':1_000_000_000,
    'overextended_ma50':.20,'overextended_return21':.30,'overextended_return63':.60}
FACTOR_LABELS = LABELS

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def merge_macro_dataset(current,prior):
    """An ephemeral CI checkout must not erase a failed provider's cloud history."""
    result=copy.deepcopy(current)
    series={s['id']:s for s in prior.get('series',[])}
    series.update({s['id']:s for s in current.get('series',[])})
    points={(p['seriesId'],p['date']):p for p in prior.get('observations',[])}
    points.update({(p['seriesId'],p['date']):p for p in current.get('observations',[])})
    sources={s['seriesId']:s for s in prior.get('sources',[])}
    sources.update({s['seriesId']:s for s in current.get('sources',[])})
    result.update(series=list(series.values()),observations=list(points.values()),sources=list(sources.values()))
    return result

def config():
    path=ROOT/'config/sector-intelligence.json'
    result=copy.deepcopy(DEFAULTS)
    if path.exists():result.update(json.loads(path.read_text(encoding='utf-8')))
    if set(result['weights'])!=set(DEFAULTS['weights']) or any(not isinstance(v,(float,int)) or not math.isfinite(v) or v<=0 for v in result['weights'].values()) or sum(result['weights'].values())!=100:
        raise ValueError('Conviction weights must be positive and sum to 100')
    if not 0<=result['watch']<result['developing']<result['high']<=100 or not 1<=result['max_industries']<=3:
        raise ValueError('Invalid conviction thresholds')
    if not 0<=result['minimum_data_quality']<=100 or result['cooldown_hours']<0 or result['score_change']<=0:raise ValueError('Invalid publication controls')
    if not 0<result['minimum_metric_weight']<=100:raise ValueError('Invalid available metric weight threshold')
    if any(not isinstance(result[k],(float,int)) or not math.isfinite(result[k]) or result[k]<=0 for k in ('overextended_ma50','overextended_return21','overextended_return63')):raise ValueError('Invalid price extension thresholds')
    return result

def edge(industry,pattern,business,order,earnings,check):
    return dict(industry=industry,pattern=pattern,business=business,order=order,earnings=earnings,check=check)

# Detailed industry labels resolve against the existing personal IDX taxonomy.
# No ticker is inserted here. A profile product match is still not revenue materiality.
GRAPH = [
 dict(id='v2_energy',title='Energy supply shock',kind='Commodity / supply',keys=['brent','wti'],pattern=r'krisis energi|pasokan minyak|selat hormuz|harga minyak',
  chain=['Gangguan pasokan energi','Harga minyak / gas dan biaya input','ASP produsen vs biaya konsumen energi','Margin, volume dan revisi laba','Ekspektasi valuasi dan repricing'],
  winners=[edge('Upstream oil & gas',r'^Oil & Gas$',r'oil|gas|petroleum',1,'ASP naik dapat meningkatkan laba jika produksi dan biaya stabil.','Produksi, realised ASP, lifting cost, hedging dan porsi hulu'),
   edge('Oilfield services',r'^Oil, Gas & Coal Supports$',r'drilling|oil|gas',2,'Capex hulu dapat menambah order jasa; harga minyak saja tidak menjamin kontrak.','Kontrak drilling, utilisasi peralatan, capex dan lag realisasi'),
   edge('Oil tankers',r'^Oil & Gas Transportation \(Tanker\)$',r'tanker|shipping',2,'Potensi manfaat dari ton-mile, tarif charter dan utilisasi; bunker mahal dapat menekan margin.','Tarif tanker, charter mix, ton-mile, bunker dan keamanan rute'),
   edge('Thermal coal',r'^Coal$',r'coal|mining',2,'Substitusi gas ke batu bara dapat mendukung margin; bukan coking coal.','Jenis batu bara, DMO, kontrak, volume dan biaya')],
  losers=[{'industry':'Air transportation','mechanism':'Fuel naik menekan margin jika tarif, subsidi atau hedging tidak menutup biaya.'},
   {'industry':'Energy-intensive manufacturing','mechanism':'Energi dan feedstock lebih mahal; uji pricing power dan pasokan kontraktual.'}],
  invalidate=['Harga energi dan gangguan pasokan berbalik; inventory pulih.','Biaya, produksi turun, regulasi atau hedging meniadakan kenaikan ASP.'],
  checks=['Supply outage / inventory vs demand','Forward curve, realised ASP, produksi dan unit cost'], reference='https://www.iea.org/reports/oil-market-report'),
 dict(id='v2_ai',title='AI infrastructure & power capex',kind='Structural capex',keys=[],pattern=r'pusat data|data cent(?:er|re)|infrastruktur ai|kecerdasan buatan',
  chain=['Capex komputasi yang dikomitmenkan','Pusat data dan koneksi listrik','Backlog kabel / peralatan / cooling','Konversi order ke revenue, margin dan kas','Valuasi relatif terhadap pertumbuhan terukur'],
  winners=[edge('Data-center infrastructure',r'Data Center',r'data cent|cloud|colocation',1,'Utilisasi dan kontrak dapat menaikkan revenue; biaya listrik dan capex harus dihitung.','Kontrak, utilisasi, MW, capex, pendapatan berulang'),
   edge('Electrical / copper cables',r'^Electrical$',r'cable|wire|electrical',2,'Order elektrifikasi dapat menambah volume dan utilisasi; kenaikan tembaga bisa menekan modal kerja.','Backlog terikat, client capex, margin dan cash conversion')],
  losers=[{'industry':'Uncontracted data centers','mechanism':'Overcapacity, koneksi grid tertunda dan capex mahal dapat menurunkan return.'}],
  invalidate=['Tidak ada konversi order material; proyek dibatalkan atau koneksi listrik tertunda.','Efisiensi AI, oversupply kapasitas atau valuasi telah mendiskontokan pertumbuhan.'],
  checks=['Committed capex, grid connection dan signed backlog','Revenue exposure dan biaya modal; AI tidak otomatis menguntungkan semua logam'],reference='https://www.iea.org/reports/energy-and-ai'),
 dict(id='v2_gold',title='Gold investment demand',kind='Commodity / monetary',keys=['gold'],pattern=r'harga emas|permintaan emas|gold rally',
  chain=['Risk / real yield / permintaan investasi','Harga jual emas','Produksi dan AISC setelah royalti / hedge','Margin dan laba produsen','Valuasi vs laba yang sudah diantisipasi'],
  winners=[edge('Gold mining',r'^Gold$',r'gold|mining',1,'Selisih realised gold price dan AISC menentukan margin, bukan harga emas saja.','Ounces, AISC, reserve life, royalti, hedging')],
  losers=[{'industry':'Price-sensitive jewellery','mechanism':'Harga tinggi dapat menekan volume perhiasan; tidak menyiratkan saham bank harus turun.'}],
  invalidate=['AISC, capex atau royalti naik lebih cepat dari realised gold price.','Volume turun atau valuasi sudah mencerminkan gold rally.'],checks=['ETF / physical demand dan real yields','Produksi, AISC, hedge dan valuasi'],reference='https://www.gold.org/goldhub/research'),
 dict(id='v2_biodiesel',title='Biodiesel policy & palm demand',kind='Policy / physical demand',keys=['cpo'],pattern=r'\bb[345]0\b|\bb35\b|biodiesel|fame',
  chain=['Mandat blending, alokasi dan pendanaan','Realisasi volume FAME dan serapan feedstock','CPO spread, pungutan dan utilisasi','Laba upstream vs margin processor / konsumen','Valuasi setelah volume dan margin terkonfirmasi'],
  winners=[edge('Palm upstream',r'^Palm Oil$|^Agricultural Products',r'palm|plantation',1,'Serapan feedstock dapat mendukung ASP; yield, biaya dan pungutan menentukan laba.','Realisasi blending, tonase CPO, produksi, yield dan margin'),
   edge('Qualified FAME processing',r'^Staple Food Producers',r'biodiesel|biofuel|fame',1,'Alokasi FAME dapat menambah utilisasi jika biaya feedstock dan insentif mendukung spread.','Bukti produsen FAME, alokasi, realisasi, subsidi dan processing margin')],
  losers=[{'industry':'Unhedged palm downstream users','mechanism':'Feedstock lebih mahal dapat mengurangi margin pengolah makanan; serapan belum sama dengan keuntungan.'}],
  invalidate=['Implementasi / pendanaan tertunda atau blending aktual tidak bertambah.','CPO supply squeeze, pungutan atau biaya meniadakan volume / ASP lebih tinggi.'],
  checks=['Keputusan resmi vs volume aktual, bukan rencana B50 saja','CPO / biodiesel spread, biaya, pungutan dan subsidi'],reference='https://www.esdm.go.id/id/media-center/arsip-berita/penetapan-alokasi-biodiesel-tahun-2023-sebesar-1315-juta-kiloliter'),
 dict(id='v2_food',title='Food supply disruption',kind='Commodity / weather',keys=['cpo','wheat'],pattern=r'krisis pangan|pasokan pangan|larangan ekspor|el nino|harga gandum|harga cpo',
  chain=['Cuaca / pembatasan pasokan komoditas tertentu','Harga crop yang tepat dan inventory','ASP produsen vs feedstock pengguna','Yield, volume, spread dan margin','Earnings expectations dan harga saham'],
  winners=[edge('Palm upstream',r'^Palm Oil$|^Agricultural Products',r'palm|plantation',1,'ASP CPO dapat membantu upstream hanya jika yield dan biaya tidak memburuk.','Komoditas spesifik, tonase, yield, CPO spread dan biaya')],
  losers=[{'industry':'Downstream food producers','mechanism':'Biaya crop naik menekan margin jika pass-through dan stok tidak mencukupi.'}],
  invalidate=['Kehilangan yield menghapus ASP lebih tinggi.','Pasokan pulih, kebijakan ekspor berubah atau harga input tidak sesuai eksposur.'],checks=['Crop-specific output, inventory dan weather','Realised ASP, yield dan margin pengguna'],reference='https://www.worldbank.org/en/research/commodity-markets'),
 dict(id='v2_monetary',title='Domestic monetary transmission',kind='Rates / credit',keys=['bi','usdidr','inflation'],pattern=r'bi[- ]rate|suku bunga|kredit|rupiah',
  chain=['BI-rate, inflasi dan rupiah','Repricing biaya dana dan bunga kredit','Affordability serta permintaan kredit','Volume, NIM, NPL dan laba','Discount rate vs earnings expectations'],
  winners=[edge('Property development',r'^Property$',r'property|real estate|residential',2,'Pelonggaran bisa membantu presales; permintaan dan akses kredit harus terkonfirmasi.','Presales, KPR, affordability, utang dan arus kas'),
   edge('Consumer financing',r'^Financing$',r'financ|credit',1,'Pendanaan lebih murah dapat membantu spread, jika yield kredit dan NPL tidak memburuk.','Funding cost, repricing, NPL dan pertumbuhan kredit')],
  losers=[{'industry':'Deposit-spread sensitive banks','mechanism':'Margin bank bergantung repricing aset/liabilitas; penurunan bunga bukan otomatis positif.'}],
  invalidate=['Rupiah / inflasi membatasi ruang easing.','Demand lemah atau NPL naik menghapus manfaat biaya dana.'],checks=['Keputusan BI, FX, inflasi dan kredit','Presales, funding cost, NIM / NPL'],reference='https://www.bi.go.id/en/statistik/indikator/bi-rate.aspx'),
 dict(id='v2_shipping',title='Shipping route disruption',kind='Logistics / capacity',keys=[],pattern=r'gangguan pelayaran|tarif angkut|tarif pengiriman|rute pelayaran|shipping disruption',
  chain=['Rute memanjang / kapasitas efektif turun','Freight rate pada rute dan vessel yang tepat','Spot exposure vs kontrak / charter','Pendapatan per voyage dikurangi bunker dan sewa','Laba dan repricing setelah biaya / valuasi'],
  winners=[edge('Exposed shipping operators',r'^Logistics & Shipment$|^Oil & Gas Transportation',r'shipping|vessel|tanker|container',1,'Freight rate dapat menaikkan laba hanya pada rute, vessel dan kontrak yang sesuai.','Spot vs long-term, rute, vessel class, owned / chartered, bunker')],
  losers=[{'industry':'Importers / exporters','mechanism':'Landed cost dan waktu pengiriman naik tanpa pass-through.'}],
  invalidate=['Rute normal, kapasitas efektif pulih atau freight rates menurun.','Sewa kapal dan bunker menyerap seluruh kenaikan tarif.'],checks=['Freight index dan port delays','Rute, kontrak dan net voyage margin'],reference='https://unctad.org/rmt2022'),
 dict(id='v2_nickel',title='Nickel capacity & profitability',kind='Supply / industrial capacity',keys=['nickel'],pattern=r'nikel|nickel|smelter',
  chain=['Tambahan smelter vs demand dan battery mix','Surplus / inventory dan harga nikel','Realised price dikurangi cash cost / debt','Margin dan kebutuhan pembiayaan','Dilusi, valuasi dan market repricing'],
  winners=[],losers=[{'industry':'High-cost nickel producers','mechanism':'Output naik bersama harga turun dapat merusak margin; low-cost advantage memerlukan data biaya.'}],
  invalidate=['Kuota atau gangguan pasokan benar-benar menyusutkan surplus.','Inventory turun dan spread kembali menutup all-in cost.'],checks=['Inventories, supply additions, demand dan LFP share','Processing route, cash cost, debt, dilution'],reference='https://www.iea.org/reports/global-critical-minerals-outlook-2025/executive-summary')
]

def valid_url(url):
    try:
        p=urlparse(url)
        return p.scheme=='https' and bool(p.hostname) and not p.username and not p.password and p.port in (None,443)
    except (ValueError,TypeError):return False

def macro_analytics(dataset,now):
    """Retain observation period separately from knowledge time; no inferred release dates."""
    output=[]
    for spec in dataset.get('series',[]):
        history=[]
        for point in dataset.get('observations',[]):
            value=point.get('value');retrieved=instant(point.get('retrievedAt'));published=instant(point.get('publishedAt'))
            if point.get('seriesId')!=spec['id'] or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):continue
            if not retrieved or retrieved>now or (published and published>now) or point['date']>now.date().isoformat():continue
            history.append({'date':point['date'],'value':value,'published_at':point.get('publishedAt'),
                'collected_at':point.get('retrievedAt'),'available_at':point.get('availableAt'),'revision':point.get('revision','unknown'),
                'checksum':point.get('rawChecksum')})
        history=sorted({p['date']:p for p in history}.values(),key=lambda p:p['date'])
        if not history:continue
        last=history[-1];prior=history[-2] if len(history)>1 else None
        age=(now.date()-datetime.fromisoformat(last['date']).date()).days
        limit={'monthly':70,'quarterly':150,'annual':800,'policy-event':180}.get(spec['frequency'],7)
        steps=21 if spec['frequency']=='daily' else 3 if spec['frequency']=='monthly' else 1
        base=history[-steps-1] if len(history)>steps else None
        pct=(last['value']/base['value']-1)*100 if base and base['value'] else None
        absolute=last['value']-base['value'] if base else None
        prev_change=(base['value']/history[-2*steps-1]['value']-1)*100 if len(history)>2*steps and history[-2*steps-1]['value'] else None
        changes=[history[i]['value']/history[i-1]['value']-1 for i in range(max(1,len(history)-120),len(history)-1) if history[i-1]['value']]
        z=None
        if len(changes)>=20 and statistics.pstdev(changes)>1e-12 and prior and prior['value']:
            z=((last['value']/prior['value']-1)-statistics.mean(changes))/statistics.pstdev(changes)
        threshold=.1 if spec['unit'].startswith('%') else 3
        measure=absolute if spec['unit'].startswith('%') else pct
        regime='insufficient' if measure is None else 'rising' if measure>=threshold else 'falling' if measure<=-threshold else 'stable'
        output.append({'id':spec['id'],'name':spec['label'],'source':spec['source'],'source_url':spec['sourceUrl'],
            'credibility':'official_dataset','retrieval_status':'failed_retained' if any(f.get('seriesId')==spec['id'] or (f.get('provider')=='World Bank Pink Sheet' and spec.get('source')=='World Bank Pink Sheet') for f in dataset.get('failures',[])) else 'received',
            'value':last['value'],'unit':spec['unit'],'frequency':spec['frequency'],'observation_date':last['date'],
            'published_at':last['published_at'],'collected_at':last['collected_at'],'revision_status':last['revision'],
            'release_time_known':bool(last['published_at']),'stale':age>limit,'age_days':age,'regime':regime,
            'change_pct':pct,'change_absolute':absolute,'previous_change_pct':prev_change,
            'acceleration_pp':pct-prev_change if pct is not None and prev_change is not None else None,
            'zscore_daily_change':z,'history':history[-180:],'baseline_date':base['date'] if base else None})
    return output

def regime_transitions(indicators,previous):
    old={x['id']:x for x in previous};changes=[]
    for item in indicators:
        prior=old.get(item['id'])
        if prior and prior['regime']!=item['regime'] and not item['stale'] and item['regime']!='insufficient':
            changes.append({'indicator':item['id'],'old':prior['regime'],'new':item['regime'],
                'reason':f"{item['name']}: {item['change_absolute']:.4g} {item['unit']} sejak {item['baseline_date']}; periode {item['observation_date']}",
                'source_url':item['source_url']})
    return changes

def joint_regimes(indicators):
    """Conditional interactions; absent leading indicators cannot imply recession."""
    by={x['id']:x for x in indicators if not x['stale']}
    def state(key):return by.get(key,{}).get('regime','unavailable')
    rows=[]
    fed=state('fed');dollar=state('dollar_broad');yields=state('ust10')
    rows.append({'id':'global_financing','state':'tightening_pressure' if fed=='rising' and (dollar=='rising' or yields=='rising') else 'easing_with_confirmation' if fed=='falling' and dollar in ('falling','stable') else 'mixed_or_insufficient',
        'inputs':['fed','ust10','dollar_broad'],'reason':'Policy, yield dan USD harus dibaca bersama; perubahan bunga sendiri bukan sinyal risk-on.'})
    spread=by['ust10']['value']-by['ust2']['value'] if 'ust10' in by and 'ust2' in by and by['ust10']['observation_date']==by['ust2']['observation_date'] else None
    rows.append({'id':'yield_curve','state':'inverted' if spread is not None and spread<0 else 'positive_slope' if spread is not None else 'insufficient',
        'value_pp':spread,'inputs':['ust10','ust2'],'reason':'10Y minus 2Y pada tanggal sama; inversi bukan bukti resesi atau target return.'})
    bi=state('bi');fx=state('usdidr');inflation=state('inflation')
    rows.append({'id':'domestic_financing','state':'easing_constrained_by_fx' if bi=='falling' and fx=='rising' else 'easing_with_stability' if bi=='falling' and fx in ('stable','falling') and inflation!='rising' else 'restrictive_pressure' if bi=='rising' or fx=='rising' else 'mixed_or_insufficient',
        'inputs':['bi','usdidr','inflation'],'reason':'Affordability, funding dan permintaan bisa membaik saat easing, tetapi FX / inflasi dapat membatasi transmisi.'})
    rows.append({'id':'growth_cycle','state':'insufficient_leading_coverage','inputs':['us_industrial','gdp','id_credit','china_pmi'],
        'reason':'GDP lagging tanpa kredit / PMI / breadth tidak cukup untuk menyatakan recovery atau recession.'})
    for r in rows:r['missing_inputs']=[key for key in r['inputs'] if key not in by]
    return rows

def verified_assertion(row,now):
    """Reviewed source-backed structured evidence, not arbitrary LLM confidence."""
    published=instant(row.get('published_at'));collected=instant(row.get('collected_at'));expiry=instant(row.get('expires_at'))
    return (isinstance(row.get('id'),str) and 0<len(row['id'])<=150 and row.get('verification')=='reviewed' and row.get('credibility') in ('official_release','issuer_filing','licensed_dataset')
        and valid_url(row.get('source_url','')) and published and collected and published<=now and collected<=now
        and expiry and expiry>now and row.get('observation_date','9999')<=now.date().isoformat()
        and bool(row.get('reason')) and bool(row.get('reviewed_by')) and bool(row.get('source_excerpt'))
        and bool(row.get('measurement_basis')) and row.get('factor') in FACTOR_LABELS
        and isinstance(row.get('score'),(float,int)) and not isinstance(row['score'],bool) and math.isfinite(row['score']) and 0<=row['score']<=100)

def score_industry(link,members,profiles,prices,indicators,theme,assertions,now,cfg,benchmark=None):
    # profiles is retained only for call compatibility; never read by this model.
    factors={k:{'value':None,'weight':w,'label':FACTOR_LABELS[k],'evidence':[],
        'reason':'Unavailable; excluded from score denominator'} for k,w in cfg['weights'].items()}
    factors['macro'].update(macro_factor(indicators,theme))
    factors['leading'].update(leading_factor(indicators,theme))
    technical=industry_features(prices,members,benchmark or [],now,cfg)
    market=technical['market'];coverage=technical['coverage_confidence']
    for key,value in technical['values'].items():
        factors[key].update(value=round(value,1) if value is not None else None,
            evidence=[market['source_url']] if market and value is not None else [],
            reason={'relative':'1/3/6 month representative returns vs actual IHSG; missing horizons excluded.',
                'momentum':'Available MA20/50/200, acceleration and previous-20-session high breakout checks.',
                'breadth':'Percentage of available representatives above MA50 with MA20 > MA50.',
                'risk':'252-session annualized daily volatility, maximum drawdown and MA reversal risk.'}[key])
    valid=[a for a in assertions if a.get('event_id')==theme['id'] and a.get('industry')==link['industry'] and verified_assertion(a,now)]
    # Reviewed external macro / physical data may supply qualitative measurement.
    # Price factors can only be computed from observed prices, never assertions.
    for key in ('macro','leading'):
        found=[a for a in valid if a['factor']==key]
        if found:factors[key].update(value=min(a['score'] for a in found),
            evidence=sorted({a['source_url'] for a in found}),reason=' / '.join(a['reason'] for a in found))
    score,included=combine_factors(factors)
    blocks=[]
    if coverage['available_stocks']<2:blocks.append('At least two independent representatives required; one stock is not industry rotation.')
    if coverage['confidence']<cfg['minimum_data_quality']:blocks.append('Data Coverage Confidence below publication threshold.')
    if factors['macro']['value'] is None:blocks.append('Fresh external macro alignment unavailable.')
    elif factors['macro']['value']<cfg['developing']:blocks.append('Macro alignment does not support the beneficiary thesis.')
    if factors['relative']['value'] is None:blocks.append('Actual IHSG relative-strength validation unavailable.')
    elif market and any(market.get('relative'+str(n)) is None for n in (21,63,126)):
        blocks.append('One or more 1/3/6-month IHSG comparisons unavailable.')
    if included<cfg['minimum_metric_weight']:blocks.append('Available metric weight below publication threshold.')
    if market and market['overextended']:blocks.append('Price rally already extended; avoid chasing, monitor consolidation.')
    if market and market['relative_stock_counts'] and min(market['relative_stock_counts'].values())<2:
        blocks.append('Relative strength supported by fewer than two representatives.')
    exposures=[{'ticker':s,'status':'watchlist_representative','business_excerpt':None,
        'source_url':'https://finance.yahoo.com/quote/'+s+'/history/','metrics':{},
        'technical':next((f for f in technical['members'] if f['ticker']==s),None)} for s in sorted(members)]
    classification='Insufficient evidence' if score is None else 'High Conviction' if score>=cfg['high'] else 'Developing Conviction' if score>=cfg['developing'] else 'Watchlist' if score>=cfg['watch'] else 'Weak / Insufficient'
    return {'industry':link['industry'],'taxonomy':sorted({m['industry'] for m in members.values()}) if isinstance(members,dict) else [],
        'order':link['order'],'earnings_effect':link['earnings'],'required_confirmation':'Macro regime, physical leading evidence and multi-stock price confirmation; company selection remains with the user.',
        'score':score if score is not None else 0,'score_available':score is not None,
        'coverage':included,'included_metric_weight':included,'missing_metrics':[k for k,v in factors.items() if v['value'] is None],
        'data_quality':coverage['confidence'],'coverage_confidence':coverage,'classification':classification,'factors':factors,
        'market':market,'exposures':exposures,'blockers':blocks,'eligible':score is not None and score>=cfg['high'] and not blocks,
        'uncertainty':'Research score, not a return probability. Missing factors excluded and remaining weights normalized; coverage assessed separately.'}


def evaluate(dataset,news,mapping,profiles,prices,assertions,previous,now=None,cfg=None,benchmark=None):
    now=now or datetime.now(timezone.utc);cfg=cfg or config()
    indicators=macro_analytics(dataset,now);lookup={x['id']:x for x in indicators};sessions=[];seen_news=set()
    # More specific events claim a headline first; a headline is never evidence for two sessions.
    for theme in sorted(GRAPH,key=lambda t:t['id']=='v2_monetary'):
        evidence=[]
        for article in sorted(news,key=lambda a:a.get('published_at') or '',reverse=True):
            stamp=instant(article.get('published_at'));collected=instant(article.get('first_seen_at'))
            norm=re.sub(r'\W+',' ',article.get('title','').casefold()).strip()
            if norm in seen_news or not approved_article(article) or not stamp or not collected or not now-timedelta(days=7)<stamp<=now or collected>now:continue
            if re.search(theme['pattern'],article['title'],re.I):
                seen_news.add(norm);evidence.append(article)
        signals=[lookup[k] for k in theme['keys'] if k in lookup]
        verified=[a for a in assertions if a.get('event_id')==theme['id'] and verified_assertion(a,now)]
        material_numeric=any(not x['stale'] and x['regime'] in ('rising','falling') for x in signals)
        if not evidence and not material_numeric and not verified:continue
        industries=[]
        for link in theme['winners']:
            members={ticker:m for ticker,m in mapping.items() if re.search(link['pattern'],m['industry'],re.I)}
            if members:industries.append(score_industry(link,members,profiles,prices,indicators,theme,assertions,now,cfg,benchmark))
        contradicted=any(a.get('invalidates') is True for a in verified)
        adverse=any(x['regime']=='rising' for x in signals if x['id'] in ('bi','usdidr')) if theme['id']=='v2_monetary' else any(x['regime']=='falling' for x in signals)
        eligible=any(i['eligible'] for i in industries) and not contradicted
        status='Invalidated' if contradicted else 'High Conviction' if eligible else 'Weakening' if adverse else 'Emerging' if material_numeric or evidence else 'Monitoring'
        required=[x for x in theme['keys'] if x not in lookup or lookup[x]['stale']]
        observations=[]
        for x in signals[:3]:
            change=f"; perubahan {x['change_pct']:+.2f}% sejak {x['baseline_date']}" if x['change_pct'] is not None else '; tren belum cukup panjang'
            observations.append(f"{x['name']} {x['value']:g} {x['unit']} (periode {x['observation_date']}{change})"+(' [perlu update]' if x['stale'] else ''))
        macro_thesis=(' | '.join(observations)+'. ' if observations else f"{len(evidence)} judul media terkait, tetapi indikator numerik khusus tema belum tersedia. ")
        macro_thesis+='Transmisi yang diuji: '+theme['chain'][1]+'. Harga / judul saja belum membuktikan kondisi supply, demand atau laba.'
        session={k:copy.deepcopy(theme[k]) for k in ('id','title','kind','chain','losers','invalidate','checks','reference')}
        session.update(methodology={'version':VERSION,'weights':cfg['weights'],'normalization':'Available factors only; coverage confidence separate','benchmark':'IHSG ^JKSE'},status=status,horizon_months=[1,3,6],score=max((i['score'] for i in industries),default=0),industries=industries,
            evidence=evidence[:8],indicators=[{k:v for k,v in x.items() if k!='history'} for x in signals],
            quantitative_charts=[{'id':x['id'],'name':x['name'],'unit':x['unit'],'source_url':x['source_url'],'frequency':x['frequency'],'points':x['history'][-65:]} for x in signals if len(x['history'])>=2][:2],
            assertions=verified,missing_indicators=required,contradicted=contradicted,
            interpretation=' → '.join(theme['chain']),macro_thesis=macro_thesis,
            forecast='Hipotesis dampak laba 1–6 bulan; belum merupakan forecast return yang tervalidasi.',
            counterargument='Kenaikan pendapatan dapat diserap biaya, supply baru, pajak, leverage atau valuasi yang sudah mahal.',
            pricing='Harga yang sudah terlalu jauh dari MA50 atau telah rally ekstrem tidak masuk shortlist. Ini ukuran extension harga, bukan valuasi fundamental.',
            scenarios={'bull':'Demand / ASP dan order terkonfirmasi, biaya terkendali, ekspektasi belum tercermin dalam valuasi.',
                'base':'Transmisi bertahap; tunggu bukti margin, kontrak, volume dan harga relatif.',
                'bear':'Pasokan / demand berbalik, biaya atau pendanaan memburuk, ekspektasi sudah priced in.'},
            reason='Bukti invalidasi terverifikasi.' if contradicted else 'Arah numerik berlawanan dengan tesis manfaat.' if adverse else 'Pemeriksaan macro–industry; publikasi menunggu seluruh execution gate.',
            confirmed=f"{len(signals)} indikator resmi terkait, {len(verified)} assertion yang ditelaah. Judul media merupakan konteks; isi belum diverifikasi.",
            updated_at=now.isoformat(),version=VERSION,research_only=True)
        # Hash excludes timestamps, article count, daily prices and methodology-only edits.
        session['content_key']=digest({'id':theme['id'],'status':status,'score_band':int(session['score']//10),
            'industries':[(i['industry'],i['eligible'],i['classification']) for i in industries],
            'contradiction_ids':sorted(a['id'] for a in verified if a.get('invalidates'))})
        sessions.append(session)
    # Reconcile an industry across themes; sum is NOT used (would reward duplicate narratives).
    ranked={}
    for s in sessions:
        for i in s['industries']:
            key=i['industry']
            if i['eligible'] and s['status']=='High Conviction':
                candidate={**i,'session_id':s['id'],'event':s['title']}
                if key not in ranked or i['score']>ranked[key]['score']:ranked[key]=candidate
    # Any validated contrary assertion for the same industry vetoes the global shortlist.
    veto={a.get('industry') for a in assertions if verified_assertion(a,now) and (a.get('invalidates') or a['score']<cfg['watch'])}
    for s in sessions:
        for i in s['industries']:
            if i['industry'] in veto:
                i['eligible']=False;i['blockers'].append('Bukti berlawanan pada sesi terkait memveto shortlist global.')
        if s['status']=='High Conviction' and not any(i['eligible'] for i in s['industries']):s['status']='Weakening'
        s['content_key']=digest({'id':s['id'],'status':s['status'],'score_band':int(s['score']//10),
            'industries':[(i['industry'],i['eligible'],i['classification']) for i in s['industries']],
            'contradiction_ids':sorted(a['id'] for a in s['assertions'] if a.get('invalidates'))})
    top=sorted((i for k,i in ranked.items() if k not in veto),key=lambda i:(-i['score'],i['industry']))[:cfg['max_industries']]
    # Downside ranking is conditional macro transmission plus observed weakness,
    # not an inverted return probability or an automatic short recommendation.
    downside=[]
    adverse_patterns={'Air transportation':r'Air Transportation',
        'Energy-intensive manufacturing':r'Construction Materials|Steel|Pulp & Paper',
        'Downstream food producers':r'Snack|Instant Noodle|Milk|Cheese|Staple Food',
        'Unhedged palm downstream users':r'Snack|Instant Noodle|Staple Food',
        'Deposit-spread sensitive banks':r'Bank',
        'High-cost nickel producers':r'^Nickel$',
        'Importers / exporters':r'Logistics & Shipment|Automobiles|Computer Hardware'}
    for s in sessions:
        for adverse in s['losers']:
            pattern=adverse_patterns.get(adverse['industry'])
            if not pattern:continue
            for label in sorted({m['industry'] for m in mapping.values() if re.search(pattern,m['industry'],re.I)}):
                members={t:m for t,m in mapping.items() if m['industry']==label}
                observed=industry_features(prices,members,benchmark or [],now,cfg)
                market=observed['market']
                if not market:continue
                price_factors={k:100-v for k,v in observed['values'].items() if v is not None}
                score=round(sum(v*cfg['weights'][k] for k,v in price_factors.items())/sum(cfg['weights'][k] for k in price_factors),1) if price_factors else None
                downside.append({'industry':label,'event':s['title'],'mechanism':adverse['mechanism'],
                    'price_pressure_score':score,'metric_weight':sum(cfg['weights'][k] for k in price_factors),
                    'coverage_confidence':observed['coverage_confidence'],'market':market,
                    'status':'conditional adverse exposure; physical/business sensitivity not verified',
                    'confirmed_industry_weakness':observed['coverage_confidence']['available_stocks']>=2 and observed['coverage_confidence']['confidence']>=cfg['minimum_data_quality'] and all(market.get('relative'+str(n)) is not None for n in (21,63,126)) and market['relative63']<0 and market['breadth_pct'] is not None and market['breadth_pct']<50,
                    'scope':'Price-pressure ranking only, distinct from beneficiary conviction. Conditional macro downside; not a short recommendation.'})
    unique_downside={}
    for item in downside:
        key=item['industry']
        if key not in unique_downside or (item['price_pressure_score'] or 0)>(unique_downside[key]['price_pressure_score'] or 0):unique_downside[key]=item
    downside=sorted(unique_downside.values(),key=lambda x:-(x['price_pressure_score'] if x['price_pressure_score'] is not None else -1))
    anomalies=[{'indicator':i['id'],'zscore':i['zscore_daily_change'],'source_url':i['source_url'],'status':'unmapped_research_question'}
        for i in indicators if not i['stale'] and i['zscore_daily_change'] is not None and abs(i['zscore_daily_change'])>=3 and not any(i['id'] in t['keys'] for t in GRAPH)]
    return {'version':VERSION,'generated_at':now.isoformat(),'sessions':sessions,'top_industries':top,
        'avoid_industries':[{'industry':x['industry'],'mechanism':x['mechanism'],'event':s['title'],'status':'conditional adverse transmission; not a short recommendation'} for s in sessions for x in s['losers']],
        'downside_ranking':[x for x in downside if x['confirmed_industry_weakness']][:5],
        'downside_watchlist':[x for x in downside if not x['confirmed_industry_weakness']],
        'empty_message':None if top else 'No New High-Conviction Sectoral Opportunity.',
        'macro':indicators,'regimes':joint_regimes(indicators),'transitions':regime_transitions(indicators,(previous or {}).get('macro',[])),
        'anomalies':anomalies,'config':cfg,'external_failures':dataset.get('failures',[]),
        'layer_status':{'deterministic':'active','price_ml':'existing price-only research model; failed validation remains gated',
            'llm':'not_configured; no autonomous causal discovery claimed','verification':'source / timestamp / IHSG benchmark / representative coverage gates active',
            'historical_macro_model':'not_validated: macro release vintages incomplete; technical diagnostic is separate from combined macro validation'},
        'data_gaps':['Company fundamentals are excluded from scoring. Full IDX coverage is not required; representative concentration is disclosed.',
            'Freight / inventories / China credit / PMI / M2 and Indonesian sector GDP coverage incomplete.',
            'Historical cases in the supplied thesis are hypotheses, not labelled training samples.'],
        'scope':'Industry research; no automated orders. Unknown releases / revisions stay unknown; no retrospective macro backtest.'}

def publication_decision(session,previous,now,cfg):
    if previous is None:return ('new_high_conviction' if session['status']=='High Conviction' and any(i['eligible'] for i in session['industries']) else None)
    old=previous['payload']
    if session['content_key']==old.get('content_key'):return None
    if old.get('version')!=session['version']:return None
    if session['contradicted'] and old['status'] not in ('Invalidated','Archived'):return 'verified_invalidation'
    if old['status'] in ('Invalidated','Archived') and session['status']!='High Conviction':return None
    strong=[i['industry'] for i in session['industries'] if i['eligible']]
    old_strong=[i['industry'] for i in old['industries'] if i['eligible']]
    changed=(strong!=old_strong or abs(session['score']-old['score'])>=cfg['score_change'] or session['status']!=old['status'])
    if not changed:return None
    urgent=any(a.get('urgent_policy') is True for a in session['assertions']) or (old['status']=='High Conviction' and not strong)
    elapsed=(now-instant(previous['published_at'])).total_seconds()/3600
    if elapsed<cfg['cooldown_hours'] and not urgent:return None
    return 'contrary_evidence_or_gate_lost' if old['status']=='High Conviction' and not strong else 'material_conviction_change'

def run_intelligence(cloud,mapping,news,prices,now=None,dataset=None,shared_context=None):
    now=now or datetime.now(timezone.utc)
    macro_file=ROOT/'public/data/macro-history.json'
    # Remote jobs with a failed download still use the last verified cloud input.
    prior_rows=read(cloud,'sector_intelligence_evaluations?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'payload','order':'generated_at.desc','limit':1}))
    prior=prior_rows[0]['payload'] if prior_rows else {}
    dataset=copy.deepcopy(dataset) if dataset is not None else json.loads(macro_file.read_text(encoding='utf-8')) if macro_file.exists() else {}
    if not dataset.get('observations'):
        contexts=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'payload','payload->intelligence_dataset':'not.is.null','order':'generated_at.desc','limit':1}))
        dataset=copy.deepcopy(contexts[0]['payload'].get('intelligence_dataset',{})) if contexts else {}
        dataset.setdefault('failures',[]).append({'provider':'macro_snapshot','error':'Local refresh unavailable; retained verified cloud snapshot'})
    from .ihsg_benchmark import benchmark_history
    benchmark=benchmark_history(cloud)
    assertions=read(cloud,'sector_evidence_assertions?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'payload','limit':1000}))
    result=evaluate(dataset,news,mapping,{},prices,[a['payload'] for a in assertions],prior,now,benchmark=benchmark)
    if shared_context:
        result['shared_analysis_id']=shared_context['analysis_id']
        systemic=[s for s in shared_context.get('signals',[]) if s['id']=='market_access']
        for session in result['sessions']:
            session['shared_analysis_id']=shared_context['analysis_id']
            session['systemic_context']=[{'title':s['title'],'state':s['state'],'impact':s['macro'],'source':(s.get('fact') or {}).get('source_url')} for s in systemic]
            session['checks']+=['Uji risiko arus modal dan likuiditas Indonesia dari konteks makro bersama; potensi manfaat laba tidak meniadakan risiko pasar.'] if systemic else []
    validation_file=ROOT/'.private/sector-model/rotation-validation.json'
    validation=json.loads(validation_file.read_text(encoding='utf8')) if validation_file.exists() else prior.get('technical_backtest')
    if validation and validation.get('weights')==result['config']['weights']:result['technical_backtest']=validation
    # JSON object keys are strings in PostgreSQL/PostgREST. Canonicalize nested
    # MA/horizon maps before hashing and exact database readback comparison.
    result=json.loads(json.dumps(result,allow_nan=False))
    heads=read(cloud,'sectoral_thesis_revisions?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'session_id,revision,published_at,payload','order':'published_at.desc','limit':200}))
    latest={}
    for r in heads:latest.setdefault(r['session_id'],r)
    publications=[]
    for session in result['sessions']:
        previous=latest.get(session['id']);reason=publication_decision(session,previous,now,result['config'])
        if reason:
            session['publication_reason']=reason
            if previous and previous['payload']['status']=='High Conviction' and not any(i['eligible'] for i in session['industries']) and not session['contradicted']:session['status']='Weakening'
            publications.append(session)
    # Missing evidence does not erase a prior thesis: publish a protective weakening once.
    for key,previous in latest.items():
        if not any(s['id']==key for s in result['sessions']) and previous['payload']['status']=='High Conviction':
            s=copy.deepcopy(previous['payload']);s.update(status='Weakening',score=0,contradicted=False,assertions=[],updated_at=now.isoformat(),reason='Bukti terkini tidak lagi mencukupi; thesis gate hilang.',publication_reason='evidence_expired')
            s['industries']=[];s['content_key']=digest({'id':key,'status':'Weakening','reason':'expired'});publications.append(s)
    # The publication transaction owns ordering, cooldown and notification deduplication.
    # Full vintage remains in the shared macro snapshot, not copied into every
    # evaluation. Charts retain only their actual displayed observations.
    for item in result['macro']:item.pop('history',None)
    stable=copy.deepcopy(result);stable.pop('generated_at',None)
    for s in stable['sessions']:s.pop('updated_at',None)
    result['evaluation_id']=digest(stable)
    existing=read(cloud,'sector_intelligence_evaluations?'+urlencode({'owner_id':'eq.'+cloud.owner,'evaluation_id':'eq.'+result['evaluation_id'],'select':'payload','limit':1}))
    coverage={'macro_status':'partial' if result['external_failures'] else 'available' if result['macro'] else 'unavailable',
        'indicator_count':len(result['macro']),'session_count':len(result['sessions'])}
    if existing and not publications:
        prior_stable=copy.deepcopy(existing[0]['payload']);prior_stable.pop('generated_at',None);prior_stable.pop('evaluation_id',None)
        for session in prior_stable['sessions']:session.pop('updated_at',None)
        if digest(prior_stable)!=result['evaluation_id']:raise CloudUnavailable('Stored evaluation hash mismatch')
        return {'published':0,'notifications_created':0,'database_verified':True,'evaluation_id':result['evaluation_id'],'eligible_industries':len(result['top_industries']),'unchanged':True,**coverage}
    outcome=cloud.request('rpc/publish_sector_intelligence',{'target_owner':cloud.owner,'evaluation':result,'proposals':publications})
    check=read(cloud,'sector_intelligence_evaluations?'+urlencode({'owner_id':'eq.'+cloud.owner,'evaluation_id':'eq.'+result['evaluation_id'],'select':'payload','limit':1}))
    if not check or check[0]['payload']!=result:raise CloudUnavailable('Intelligence evaluation readback mismatch')
    for p in publications:
        found=read(cloud,'sectoral_thesis_revisions?'+urlencode({'owner_id':'eq.'+cloud.owner,'session_id':'eq.'+p['id'],'order':'revision.desc','select':'payload','limit':1}))
        if not found or found[0]['payload'].get('content_key')!=p['content_key']:raise CloudUnavailable('Thesis publication readback mismatch')
    return {**outcome,'database_verified':True,'evaluation_id':result['evaluation_id'],'eligible_industries':len(result['top_industries']),**coverage}

def intelligence_snapshot(cloud,session_id=None,revision=None):
    if session_id and not re.fullmatch(r'v2_[a-z_]{1,50}',session_id):raise ValueError('Invalid session')
    if revision is not None and (not isinstance(revision,int) or revision<1):raise ValueError('Invalid revision')
    rows=read(cloud,'sector_intelligence_evaluations?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'payload','order':'generated_at.desc','limit':1}))
    filters={'owner_id':'eq.'+cloud.owner,'select':'session_id,revision,published_at,reason,payload','order':'published_at.desc','limit':200}
    if session_id:filters['session_id']='eq.'+session_id
    if revision:filters['revision']='eq.'+str(revision)
    revisions=read(cloud,'sectoral_thesis_revisions?'+urlencode(filters))
    return {'evaluation':rows[0]['payload'] if rows else None,'revisions':revisions,'selected':revisions[0] if session_id and revisions else None}
