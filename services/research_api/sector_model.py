"""Experimental price-only sector model with purged, chronological validation.

Current watchlist baskets are NOT official IDX sector indices. News/macro values
without historical availability timestamps are deliberately not training inputs.
"""
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from .cloud import SupabaseStore, CloudUnavailable
from .market_news import read
from .rights import ROOT, rights_record

VERSION='sector-price-research-v1'
HORIZONS=(21,63,126)
FEATURES=('momentum21','momentum63','momentum126','relative21','relative63','volatility21','downside21','turnover_ratio')
BIAS_NOTES=[
 'Survivorship/selection bias: hanya saham watchlist aktif saat ini; saham delisting dan anggota sektor historis belum direkonstruksi.',
 'Basket riset memakai klasifikasi pribadi saat ini, bukan indeks sektoral resmi IDX. Benchmark adalah rata-rata setara basket riset, bukan IHSG.',
 'Label horizon panjang saling tumpang tindih; baris antar sektor juga berkorelasi. Interval bootstrap memakai blok tanggal, bukan asumsi baris independen.',
 'Harga adjusted-close direkonstruksi vendor dan dapat direvisi. Likuiditas, slippage, pajak serta ketersediaan eksekusi aktual tidak diverifikasi.',
 'Berita, angka makro dan tanggal rilis historis belum cukup untuk backtest point-in-time. Fitur tersebut tidak dimasukkan ke model harga.',
 'Hak penggunaan/training provider belum diverifikasi sebagai lisensi produksi. Hasil ini eksperimen riset pribadi; tidak dipromosikan menjadi model produksi.'
]

def universe(cloud):
    tree=cloud.sector_tree();mapping={}
    for sector in tree['sectors']:
        for industry in sector['industries']:
            for stock in industry['stocks']:mapping[stock['symbol']]={'sector':sector['code'],'sector_name':sector['name'],'industry':industry['name']}
    if not mapping:raise CloudUnavailable('No classified active stocks for sector research')
    return mapping

def load_prices(cloud,mapping,full=False,use_cache=False):
    start='2021-01-01' if full else (datetime.now(timezone.utc).date()-timedelta(days=430)).isoformat()
    identity=hashlib.sha256(json.dumps({'universe':mapping,'start':start},sort_keys=True).encode()).hexdigest()
    cache=ROOT/'.private/sector-model'/('prices-'+identity+'.json')
    if use_cache and cache.exists():return json.loads(cache.read_text(encoding='utf-8'))
    symbols=sorted(mapping);chunks=[symbols[i:i+10] for i in range(0,len(symbols),10)]
    def fetch(chunk):
        result=[]
        for offset in range(0,20000,1000):
            page=read(cloud,'stock_prices_daily?'+urlencode({'owner_id':'eq.'+cloud.owner,'ticker':'in.('+','.join(chunk)+')',
                'trade_date':'gte.'+start,'select':'ticker,trade_date,close,adjusted_close,volume','order':'ticker,trade_date','limit':1000,'offset':offset}))
            result.extend(page)
            if len(page)<1000:return result
        raise CloudUnavailable('Price input bounded limit exceeded')
    with ThreadPoolExecutor(max_workers=4) as pool:rows=[r for batch in pool.map(fetch,chunks) for r in batch]
    if use_cache:
        cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text(json.dumps(rows,allow_nan=False),encoding='utf-8')
    return rows

def feature_panel(rows,mapping):
    import numpy as np
    import pandas as pd
    from .idx_calendar import session_dates
    df=pd.DataFrame(rows)
    if df.empty:raise ValueError('No historical stock data')
    if df.duplicated(['ticker','trade_date']).any():raise ValueError('Duplicate ticker/date in model inputs')
    for c in ('close','adjusted_close','volume'):df[c]=pd.to_numeric(df[c],errors='coerce')
    if df['trade_date'].max()>datetime.now(timezone.utc).date().isoformat():raise ValueError('Future prices rejected')
    accepted=[];excluded=[]
    for ticker,g in df.groupby('ticker'):
        if ticker not in mapping:continue
        if len(g)<150 or not np.isfinite(g[['close','adjusted_close','volume']]).all().all() or (g['adjusted_close']<=0).any() or (g['close']<=0).any() or (g['volume']<0).any():excluded.append(ticker)
        else:accepted.append(ticker)
    df=df[df.ticker.isin(accepted)]
    if df.empty:raise ValueError('No sufficiently complete adjusted-price series')
    sessions=session_dates(df.trade_date.min(),df.trade_date.max());dates=pd.Index(sessions,name='date')
    prices=df.pivot(index='trade_date',columns='ticker',values='adjusted_close').reindex(dates)
    turnover=df.assign(turnover=df.close*df.volume).pivot(index='trade_date',columns='ticker',values='turnover').reindex(dates)
    returns=prices.pct_change(fill_method=None)
    sector_returns={};sector_turnover={};coverage={}
    for sector in sorted({m['sector'] for m in mapping.values()}):
        tickers=[s for s in accepted if mapping[s]['sector']==sector]
        if not tickers:continue
        # A stock is eligible only from its first observed bar. No backward fill.
        listed=prices[tickers].notna().cummax().sum(axis=1)
        count=returns[tickers].notna().sum(axis=1)
        enough=(count>=np.maximum(1,np.ceil(listed*.7)))
        sector_returns[sector]=returns[tickers].mean(axis=1).where(enough)
        sector_turnover[sector]=turnover[tickers].sum(axis=1,min_count=1).where(enough)
        coverage[sector]={'stocks':len(tickers),'tickers':tickers,'last_coverage':float(count.iloc[-1]/max(1,listed.iloc[-1]))}
    daily=pd.DataFrame(sector_returns,index=dates)
    benchmark=daily.mean(axis=1).where(daily.notna().sum(axis=1)>=math.ceil(daily.shape[1]*.7))
    def compounded(series,n):return (1+series).rolling(n,min_periods=n).apply(np.prod,raw=True)-1
    records=[];latest=[]
    for sector in daily:
        r=daily[sector];tv=sector_turnover[sector]
        f=pd.DataFrame({'momentum21':compounded(r,21),'momentum63':compounded(r,63),'momentum126':compounded(r,126),
            'relative21':compounded(r,21)-compounded(benchmark,21),'relative63':compounded(r,63)-compounded(benchmark,63),
            'volatility21':r.rolling(21).std()*np.sqrt(252),'downside21':r.clip(upper=0).rolling(21).std()*np.sqrt(252),
            'turnover_ratio':tv.rolling(21).mean()/tv.rolling(63).mean()},index=dates).replace([np.inf,-np.inf],np.nan)
        # Require continuous returns over every feature window; missing prices stay missing.
        f=f.where(compounded(r,126).notna(),np.nan)
        for i,day in enumerate(dates):
            values=f.loc[day,list(FEATURES)]
            if values.isna().any():continue
            base={'date':day,'session_index':i,'sector':sector,'x':[float(v) for v in values]}
            if i==len(dates)-1:latest.append(base)
            if i%5:continue  # weekly sample, not a random row split
            for h in HORIZONS:
                if i+h>=len(dates):continue
                sr=r.iloc[i+1:i+h+1];br=benchmark.iloc[i+1:i+h+1]
                if sr.isna().any() or br.isna().any():continue
                actual=float((1+sr).prod()-1);reference=float((1+br).prod()-1)
                records.append({**base,'horizon':h,'label_end':dates[i+h],'excess':actual-reference,'actual_return':actual,'benchmark_return':reference})
    audit={'start':dates[0],'end':dates[-1],'sessions':len(dates),'input_rows':len(rows),'accepted_stocks':len(accepted),'excluded_stocks':excluded,
        'universe_tickers':sorted(mapping),'no_price_stocks':sorted(set(mapping)-{r['ticker'] for r in rows}),
        'sectors':coverage,'missing_prices_forward_filled':False}
    return records,latest,audit

def splits(records,horizon):
    dates=sorted({r['date'] for r in records if r['horizon']==horizon})
    if len(dates)<104:raise ValueError('Fewer than 104 weekly dates for purged evaluation')
    size=min(26,(len(dates)-52)//3)
    for fold in range(3):
        start=len(dates)-(3-fold)*size;test_dates=set(dates[start:start+size]);test_start=dates[start]
        train=[r for r in records if r['horizon']==horizon and r['label_end']<test_start]
        test=[r for r in records if r['horizon']==horizon and r['date'] in test_dates]
        if len({r['date'] for r in train})<40:continue
        assert max(r['label_end'] for r in train)<min(r['date'] for r in test)
        yield train,test

def metrics(y,p,returns,forecasts,baseline_p):
    import numpy as np
    from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score,mean_absolute_error
    y=np.asarray(y);p=np.clip(np.asarray(p),1e-6,1-1e-6);base=np.clip(np.asarray(baseline_p),1e-6,1-1e-6)
    bins=[]
    for lo,hi in zip(np.linspace(0,1,6)[:-1],np.linspace(0,1,6)[1:]):
        mask=(p>=lo)&(p<(hi if hi<1 else 1.00001))
        if mask.any():bins.append({'count':int(mask.sum()),'predicted':float(p[mask].mean()),'observed':float(y[mask].mean())})
    alerts=(p>=.6)&(np.asarray(forecasts)>.005)
    return {'samples':len(y),'accuracy':float(((p>=.5)==y).mean()),'auc':float(roc_auc_score(y,p)) if len(set(y))==2 else None,
        'brier_loss':float(brier_score_loss(y,p)),'baseline_brier':float(brier_score_loss(y,base)),
        'log_loss':float(log_loss(y,p,labels=[0,1])),'baseline_log_loss':float(log_loss(y,base,labels=[0,1])),
        'probability_bias':float(p.mean()-y.mean()),'ece':sum(b['count']*abs(b['predicted']-b['observed']) for b in bins)/len(y),
        'return_mae':float(mean_absolute_error(returns,forecasts)),'return_bias':float(np.mean(np.asarray(forecasts)-returns)),
        'baseline_return_mae':float(np.mean(np.abs(returns))),
        'alert_samples':int(alerts.sum()),'false_discovery_rate':float((1-y[alerts]).mean()) if alerts.any() else None,
        'mean_alert_excess_net_assumed_cost':float(np.asarray(returns)[alerts].mean()-.005) if alerts.any() else None,'calibration_bins':bins}

def train_model(rows,mapping):
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression,Ridge
    records,latest,audit=feature_panel(rows,mapping);sectors=sorted(audit['sectors'])
    def matrix(batch):return np.asarray([r['x']+[float(r['sector']==s) for s in sectors] for r in batch])
    models=[]
    for h in HORIZONS:
        output=[];folds=[]
        for training,testing in splits(records,h):
            x=matrix(training);y=np.asarray([int(r['excess']>0) for r in training]);target=np.asarray([r['excess'] for r in training])
            if len(set(y))<2:continue
            scaler=StandardScaler().fit(x);classifier=LogisticRegression(C=.25,max_iter=1500,random_state=42).fit(scaler.transform(x),y)
            regressor=Ridge(alpha=10).fit(scaler.transform(x),target)
            prob=classifier.predict_proba(scaler.transform(matrix(testing)))[:,1];forecast=regressor.predict(scaler.transform(matrix(testing)))
            batch=[{**r,'probability':float(p),'forecast':float(v),'baseline':float(y.mean())} for r,p,v in zip(testing,prob,forecast)]
            output.extend(batch)
            score=metrics([int(r['excess']>0) for r in batch],[r['probability'] for r in batch],np.asarray([r['excess'] for r in batch]),[r['forecast'] for r in batch],[r['baseline'] for r in batch])
            folds.append({'train_last_date':max(r['date'] for r in training),'train_last_label_end':max(r['label_end'] for r in training),
                'test_start':min(r['date'] for r in testing),'test_end':max(r['date'] for r in testing),'train_samples':len(training),'metrics':score})
        if not output:continue
        score=metrics([int(r['excess']>0) for r in output],[r['probability'] for r in output],np.asarray([r['excess'] for r in output]),[r['forecast'] for r in output],[r['baseline'] for r in output])
        # Date-block bootstrap of paired Brier improvement; overlap block >= horizon.
        per_date={}
        for r in output:per_date.setdefault(r['date'],[]).append((r['baseline']-int(r['excess']>0))**2-(r['probability']-int(r['excess']>0))**2)
        gains=np.asarray([np.mean(per_date[d]) for d in sorted(per_date)]);block=math.ceil(h/5);rng=np.random.default_rng(42);boot=[]
        for _ in range(300):
            starts=rng.integers(0,len(gains),size=math.ceil(len(gains)/block))
            sample=np.concatenate([gains[(np.arange(block)+start)%len(gains)] for start in starts])[:len(gains)]
            boot.append(float(sample.mean()))
        interval=[float(x) for x in np.quantile(boot,[.025,.975])]
        independent=len(gains)/block
        score.update(brier_improvement_ci95=interval,brier_skill=1-score['brier_loss']/score['baseline_brier'],independent_horizon_windows=round(independent,2),unique_test_dates=len(gains))
        passed=len(folds)==3 and interval[0]>0 and independent>=12 and abs(score['probability_bias'])<=.1 and score['return_mae']<score['baseline_return_mae']
        train=[r for r in records if r['horizon']==h];x=matrix(train);y=np.asarray([int(r['excess']>0) for r in train]);scaler=StandardScaler().fit(x)
        classifier=LogisticRegression(C=.25,max_iter=1500,random_state=42).fit(scaler.transform(x),y);regressor=Ridge(alpha=10).fit(scaler.transform(x),[r['excess'] for r in train])
        models.append({'horizon':h,'approx_months':{21:1,63:3,126:6}[h],'metrics':score,'folds':folds,'statistical_gate_passed':passed,
            'deployment_status':'research_only','train_last_label_end':max(r['label_end'] for r in train),
            'parameters':{'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'class_coef':classifier.coef_[0].tolist(),'class_intercept':float(classifier.intercept_[0]),'return_coef':regressor.coef_.tolist(),'return_intercept':float(regressor.intercept_)}})
    if len(models)!=3:raise ValueError('All 1/3/6-month horizons require successful evaluation')
    report={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'audit':audit,'models':models,'sector_order':sectors,
        'features':list(FEATURES),'bias_notes':BIAS_NOTES,'point_in_time_news_backtest':False,'provider_rights':rights_record('yahoo'),
        'target':'Outperform equally weighted research-sector peer basket over 21/63/126 IDX sessions; not absolute return or IHSG outperformance.',
        'cost_assumption':'.5% roundtrip assumed only for descriptive forward-return alert diagnostics; no overlapping-position CAGR/Sharpe is claimed.',
        'validation':'3 expanding chronological folds; labels must mature before each test starts; all scaling fit on training only; fixed hyperparameters, no test-set tuning.'}
    report['model_id']=hashlib.sha256(json.dumps(report,sort_keys=True,allow_nan=False).encode()).hexdigest()
    report['current_predictions']=predict(report,latest)
    return report

def predict(report,latest):
    result=[]
    for item in latest:
        values=item['x']+[float(item['sector']==s) for s in report['sector_order']]
        for model in report['models']:
            p=model['parameters'];scaled=[(x-m)/s for x,m,s in zip(values,p['mean'],p['scale'])]
            z=sum(x*w for x,w in zip(scaled,p['class_coef']))+p['class_intercept']
            probability=1/(1+math.exp(-max(-40,min(40,z))))
            result.append({'sector':item['sector'],'date':item['date'],'horizon':model['horizon'],'approx_months':model['approx_months'],
                'probability':probability,'expected_excess_return':sum(x*w for x,w in zip(scaled,p['return_coef']))+p['return_intercept'],
                'statistical_gate_passed':model['statistical_gate_passed'],'deployment_status':'research_only'})
    return result

def save_model(cloud,report):
    row={'owner_id':cloud.owner,'model_id':report['model_id'],'generated_at':report['generated_at'],'report':report}
    cloud.request('sector_model_runs?on_conflict=owner_id,model_id',[row],prefer='resolution=ignore-duplicates,return=representation')
    checked=read(cloud,'sector_model_runs?'+urlencode({'owner_id':'eq.'+cloud.owner,'model_id':'eq.'+report['model_id'],'select':'report','limit':1}))
    if not checked or checked[0]['report']!=report:raise CloudUnavailable('Sector model readback mismatch')
    return {'database_verified':True,'model_id':report['model_id']}

def latest_model(cloud,model_id=None):
    filters={'owner_id':'eq.'+cloud.owner,'select':'report','order':'generated_at.desc','limit':1}
    if model_id:filters['model_id']='eq.'+model_id
    rows=read(cloud,'sector_model_runs?'+urlencode(filters))
    return rows[0]['report'] if rows else None
