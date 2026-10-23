"""Compact durable research memory. No backfilled predictions or invented labels."""
import json,statistics
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from collections import Counter,defaultdict
from .market_news import read
from .cloud import CloudUnavailable
from .indonesia_intelligence import digest,settings

def save(cloud,kind,key,value):
    payload={'kind':kind,'key':key,'items':[],**value};identity=digest(payload)
    cloud.request('sector_macro_context?on_conflict=owner_id,snapshot_id',[{'owner_id':cloud.owner,'snapshot_id':identity,'generated_at':datetime.now(timezone.utc).isoformat(),'payload':payload}],prefer='resolution=ignore-duplicates,return=minimal')
    found=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'snapshot_id':'eq.'+identity,'select':'payload','limit':1}))
    if not found or found[0]['payload']!=payload:raise CloudUnavailable('Research memory readback mismatch')
    return identity

def realized_outcomes(theses,prices,benchmark,today):
    """Frozen publication members; never replace them with today's survivors.

    Close-price returns exclude dividends on both sides. Source revisions and
    incomplete macro vintages keep these diagnostics out of production training.
    """
    b={r['trade_date']:float(r['close']) for r in benchmark if r['trade_date']<=today};calendar=sorted(b);p=defaultdict(dict)
    for r in prices:
        if r['trade_date']<=today and r.get('close') and r['close']>0:p[r['ticker']][r['trade_date']]=float(r['close'])
    outcomes=[];pending=0
    for record in theses:
        thesis=record['payload'];published=record['published_at'][:10]
        for industry in thesis.get('industries',[]):
            if not industry.get('eligible'):continue
            base=(industry.get('market') or {}).get('date')
            members=sorted({e['ticker'] for e in industry.get('exposures',[]) if e.get('technical')})
            # Assessment starts at the first session strictly AFTER publication,
            # avoiding an untradeable same-close signal / realized return.
            candidates=[d for d in calendar if d>published]
            if not candidates or not members:pending+=3;continue
            entry=candidates[0];idx=calendar.index(entry)
            for horizon in settings()['prediction_horizons_sessions']:
                if idx+horizon>=len(calendar):pending+=1;continue
                end=calendar[idx+horizon];available=[s for s in members if entry in p[s] and end in p[s]]
                coverage=len(available)/len(members)
                key=digest([record['session_id'],record['revision'],industry['industry'],horizon])
                result={'outcome_id':key,'session_id':record['session_id'],'revision':record['revision'],'industry':industry['industry'],
                    'published_at':record['published_at'],'horizon_sessions':horizon,'entry_date':entry,'end_date':end,'frozen_members':members,
                    'available_members':available,'coverage':coverage,'conviction':industry['score'],'model_version':thesis.get('version'),
                    'status':'evaluated' if coverage==1 and len(available)>=2 else 'insufficient_coverage','return':None,'ihsg_return':b[end]/b[entry]-1,'excess_return':None,
                    'point_in_time_training_ready':False,'basis':'next-session close entry; equal-weight close-price return vs IHSG price return; dividends excluded; revisions not reconstructed'}
                if result['status']=='evaluated':
                    result['return']=statistics.mean(p[s][end]/p[s][entry]-1 for s in available)
                    result['excess_return']=result['return']-result['ihsg_return'];result['direction_correct']=result['excess_return']>0
                outcomes.append(result)
    return outcomes,pending

def maintain_memory(cloud,now=None):
    now=now or datetime.now(timezone.utc);today=now.date().isoformat();cfg=settings();policies=cfg['retention']
    reports=read(cloud,'daily_market_analysis?'+urlencode({'owner_id':'eq.'+cloud.owner,'method':'eq.indonesia-first-v2.0','select':'report_date,report','order':'report_date.desc,generated_at.desc','limit':500}))
    days={}
    for row in reports:days.setdefault(row['report_date'],row['report'])
    monthly=defaultdict(list)
    for day,report in days.items():monthly[day[:7]].append((day,report['brief']))
    saved=[]
    for month,rows in monthly.items():
        if month>=today[:7]:continue
        value={'month':month,'days':len(rows),'economic_regimes':dict(Counter(b['economic_regime']['current'] for _,b in rows)),
            'equity_regimes':dict(Counter(b['equity_regime']['current'] for _,b in rows)),
            'states':[{'date':day,'economic':b['economic_regime']['current'],'equity':b['equity_regime']['current'],'ihsg':b['observed_prices'].get('^JKSE'),'rupiah':b['observed_prices'].get('IDR=X'),'missing_inputs':b['missing_inputs']} for day,b in sorted(rows)],
            'scope':'Compact structured memory, not training labels.'}
        saved.append(save(cloud,'intelligence_monthly_summary',month,value))
    from .ihsg_benchmark import benchmark_history
    theses=read(cloud,'sectoral_thesis_revisions?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'session_id,revision,published_at,payload','order':'published_at','limit':1000}))
    frozen=sorted({e['ticker'] for r in theses for i in r['payload'].get('industries',[]) if i.get('eligible') for e in i.get('exposures',[])})
    prices=[]
    if frozen:
        from .sector_model import load_prices
        prices=load_prices(cloud,{s:{} for s in frozen},full=True)
    outcomes,pending=realized_outcomes(theses,prices,benchmark_history(cloud),today)
    for outcome in outcomes:saved.append(save(cloud,'intelligence_prediction_outcome',outcome['outcome_id'],{'outcome':outcome}))
    by_horizon={}
    for horizon in (21,63,126):
        valid=[r for r in outcomes if r['horizon_sessions']==horizon and r['status']=='evaluated']
        by_horizon[str(horizon)]={'samples':len(valid),'directional_accuracy':statistics.mean(r['direction_correct'] for r in valid) if valid else None,'mean_excess_return':statistics.mean(r['excess_return'] for r in valid) if valid else None,'model_trained':False,'walk_forward_validation':'pending sufficient timestamped macro vintages and labels'}
    storage=cloud.storage()
    audit={'week':f'{now.isocalendar().year}-W{now.isocalendar().week:02}','distinct_daily_states':len(days),'monthly_summaries':len(monthly),'mature_outcomes':len(outcomes),'pending_horizons':pending,'outcomes_by_horizon':by_horizon,
        'storage':storage,'project_database_limit_bytes':cfg['project_database_limit_bytes'],'quota_status':cfg['database_limit_status'],
        'retention':{'policy':policies,'mode':'preview_only','candidates_detailed_reports':sum(day<(now.date()-timedelta(days=policies['detailed_reports_days'])).isoformat() for day in days),'preserved':['observation histories','structured daily states','monthly summaries','all published thesis revisions','prediction outcomes'],'reason':'No irreversible cloud deletion during development. Review the compact archive before enabling destructive cleanup.'},
        'model_status':'hybrid heuristic research; no return model trained or validated'}
    key=save(cloud,'intelligence_memory_audit',today,audit)
    return {'database_verified':True,'audit_id':key,'monthly_summary_writes':len(saved),'outcomes':by_horizon,'pending_horizons':pending,'retention_mode':'preview_only'}
