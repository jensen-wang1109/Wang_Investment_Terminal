"""Fundamental-free, deterministic research factors; never return probabilities.

Available representatives are equal weighted. The benchmark is actual IHSG,
not the application watchlist. Missing observations are never interpolated.
"""
import math
import statistics
from datetime import date, timedelta, timezone

WEIGHTS={'macro':25,'leading':20,'relative':20,'momentum':15,'breadth':10,'risk':10}
LABELS={'macro':'Macro Alignment','leading':'Commodity & Leading Indicators',
    'relative':'Relative Strength vs IHSG','momentum':'Price Momentum & Trend',
    'breadth':'Industry Breadth','risk':'Risk & Volatility'}

def number(v):
    return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)

def clamp(v):return max(0.,min(100.,v))

def observations(rows,cutoff):
    points={};duplicates=set()
    for row in rows:
        day=row.get('trade_date','9999');value=row.get('close')
        if day>cutoff or not number(value) or value<=0:continue
        if day in points:duplicates.add(day)
        points[day]=value
    return {k:v for k,v in points.items() if k not in duplicates}

def stock_features(rows,benchmark,now,cfg):
    cutoff=now.astimezone(timezone(timedelta(hours=7))).date().isoformat()
    b=observations(benchmark,cutoff);p=observations(rows,cutoff)
    calendar=sorted(b);last=calendar[-1] if calendar else None
    if not last or last not in p or (now.date().isoformat()>last and (now.date()-date.fromisoformat(last)).days>7):return None
    window=calendar[-252:];days=sorted(d for d in p if d<=last);values=[p[d] for d in days]
    if len(values)<20:return None
    last_price=p[last];moving={n:statistics.mean(values[-n:]) if len(values)>=n else None for n in (20,50,200)}
    relative={};returns={}
    for n in (21,63,126):
        if len(calendar)<=n:continue
        span=calendar[-n-1:];base=span[0]
        if base not in p or sum(d in p for d in span)/len(span)<.9:continue
        returns[n]=last_price/p[base]-1
        relative[n]=returns[n]-(b[last]/b[base]-1)
    # No return across a missing exchange session is represented as a daily return.
    changes=[p[calendar[i]]/p[calendar[i-1]]-1 for i in range(max(1,len(calendar)-252),len(calendar)) if calendar[i] in p and calendar[i-1] in p]
    vol=statistics.stdev(changes)*math.sqrt(252) if len(changes)>=20 else None
    peak=values[-min(252,len(values))];drawdown=0.
    for value in values[-252:]:peak=max(peak,value);drawdown=min(drawdown,value/peak-1)
    prior_high=max(values[-21:-1]) if len(values)>=21 else None
    checks=[]
    for n,ma in moving.items():
        if ma is not None:checks.append(100. if last_price>ma else 0.)
    if moving[20] is not None and moving[50] is not None:checks.append(100. if moving[20]>moving[50] else 0.)
    accelerating=None
    if 21 in returns and len(calendar)>42 and calendar[-43] in p and calendar[-22] in p:
        accelerating=returns[21]-(p[calendar[-22]]/p[calendar[-43]]-1)
        checks.append(clamp(50+accelerating*500))
    breakout=last_price>prior_high if prior_high is not None else None
    if breakout is not None:checks.append(100. if breakout else 0.)
    distance=last_price/moving[50]-1 if moving[50] is not None else None
    extended=(distance is not None and distance>cfg.get('overextended_ma50',.20)) or returns.get(21,0)>cfg.get('overextended_return21',.30) or returns.get(63,0)>cfg.get('overextended_return63',.60)
    # A reduced MA set stays visible, with coverage penalty outside the score.
    momentum=statistics.mean(checks) if checks else None
    reversal=bool(moving[20] is not None and moving[50] is not None and last_price<moving[20]<moving[50])
    risk=clamp(100-(vol*70+abs(drawdown)*70+(20 if reversal else 0))) if vol is not None else None
    turnovers=[r['close']*r['volume'] for r in rows if r.get('trade_date') in set(window[-21:]) and number(r.get('close')) and number(r.get('volume')) and r['volume']>=0]
    return {'date':last,'observations':len(values),'history_completeness':sum(d in p for d in window)/len(window),
        'returns':returns,'relative':relative,'ma':moving,'momentum':momentum,'acceleration':accelerating,
        'breakout':breakout,'overextended':extended,'distance_ma50':distance,'volatility':vol,
        'max_drawdown':drawdown,'reversal':reversal,'risk':risk,
        'positive_trend':last_price>moving[50] and moving[20]>moving[50] if moving[50] is not None else None,
        'turnover':statistics.median(turnovers) if turnovers else None}

def industry_features(prices,tickers,benchmark,now,cfg):
    groups={s:[] for s in tickers}
    for row in prices:
        if row.get('ticker') in groups:groups[row['ticker']].append(row)
    available={s:f for s,rows in groups.items() if (f:=stock_features(rows,benchmark,now,cfg)) is not None}
    count=len(available);expected=len(tickers);complete=statistics.mean(f['history_completeness'] for f in available.values()) if count else 0
    history_depth=statistics.mean(min(f['observations']/200,1) for f in available.values()) if count else 0
    # Count/concentration proxy, not a claim about market-cap or full IDX coverage.
    representation=1-1/count if count else 0
    confidence=round(35*min(count/3,1)+40*complete*history_depth*(count/expected if expected else 0)+25*representation,1)
    coverage={'confidence':confidence,'available_stocks':count,'tracked_stocks':expected,
        'historical_completeness':round(complete*100,1),'history_depth':round(history_depth*100,1),
        'representativeness_proxy':round(representation*100,1),'universe':'available personal watchlist representatives',
        'method':'35% stock count (cap 3) + 40% history completeness/depth/availability + 25% equal-weight diversification',
        'limitations':['Full IDX industry universe and economic exposure are not verified.',
            'One stock cannot confirm industry rotation. Equal weighting is not a sector-index return.']}
    if not available:return {'coverage_confidence':coverage,'market':None,'values':{},'members':[]}
    mean=lambda key:statistics.mean(f[key] for f in available.values() if f[key] is not None) if any(f[key] is not None for f in available.values()) else None
    rs={n:statistics.mean(f['relative'][n] for f in available.values() if n in f['relative']) for n in (21,63,126) if any(n in f['relative'] for f in available.values())}
    rs_count={n:sum(n in f['relative'] for f in available.values()) for n in rs}
    rs_score=statistics.mean(clamp(50+v*500) for v in rs.values()) if rs else None
    trends=[f['positive_trend'] for f in available.values() if f['positive_trend'] is not None]
    breadth=100*sum(trends)/len(trends) if trends else None
    extended=sum(f['overextended'] for f in available.values())/count>=.5
    market={'date':max(f['date'] for f in available.values()),'benchmark':'^JKSE','source_url':'https://finance.yahoo.com/quote/%5EJKSE/history/',
        'relative21':rs.get(21),'relative63':rs.get(63),'relative126':rs.get(126),'relative_stock_counts':rs_count,
        'return21':statistics.mean(f['returns'][21] for f in available.values() if 21 in f['returns']) if 21 in rs else None,
        'turnover_idr':mean('turnover'),'annualized_volatility':mean('volatility'),'max_drawdown':mean('max_drawdown'),
        'breadth_pct':breadth,'overextended':extended,'stage':'Extended / avoid chasing' if extended else 'Emerging / needs macro confirmation' if rs.get(21,0)>0 and rs.get(63,0)<=0 else 'Confirmed trend' if rs.get(21,0)>0 and rs.get(63,0)>0 else 'Unconfirmed / weak',
        'reason':'Equal-weight representative close-price returns minus actual IHSG price return over identical 21/63/126-session endpoints; dividends excluded on both sides.'}
    return {'coverage_confidence':coverage,'market':market,
        'values':{'relative':rs_score,'momentum':mean('momentum'),'breadth':breadth,'risk':mean('risk')},
        'members':[{'ticker':s,**f} for s,f in sorted(available.items())]}

def combine_factors(factors):
    available=sum(f['weight'] for f in factors.values() if f['value'] is not None)
    return (round(sum(f['value']*f['weight'] for f in factors.values() if f['value'] is not None)/available,1) if available else None,available)

def macro_factor(indicators,theme):
    by={x['id']:x for x in indicators if not x['stale'] and x['regime']!='insufficient'}
    values=[];reasons=[];sources=[]
    for key in ('fed','bi','usdidr','inflation','dollar_broad','us_industrial','gdp'):
        x=by.get(key)
        if not x:continue
        state=x['regime'];gold=theme['id']=='v2_gold'
        # Explicit conditional transmission, not a learned return prediction.
        if key in ('fed','bi','inflation','dollar_broad'):
            score={'falling':80.,'stable':60.,'rising':25.}[state]
        elif key=='usdidr':score={'falling':75.,'stable':60.,'rising':35.}[state]
        else:score={'rising':75.,'stable':55.,'falling':65. if gold else 25.}[state]
        values.append(score);reasons.append(f"{x['name']}: {state} ({x['observation_date']})");sources.append(x['source_url'])
    return {'value':round(statistics.mean(values),1) if values else None,'evidence':sorted(set(sources)),
        'reason':'; '.join(reasons)+'. Easing/liquidity and growth transmission is conditional; currency pressure reduces alignment.' if values else 'Global/domestic macro regime observations unavailable; headline counts do not fill this factor.'}

def leading_factor(indicators,theme):
    relevant=[x for x in indicators if x['id'] in theme['keys'] and x['id'] not in ('bi','inflation','usdidr') and not x['stale'] and x['regime']!='insufficient']
    if not relevant:return {'value':None,'evidence':[],'reason':'Relevant commodity / physical leading series unavailable. No neutral score imputed.'}
    values=[{'rising':80.,'stable':50.,'falling':20.}[x['regime']] for x in relevant]
    return {'value':round(statistics.mean(values),1),'evidence':sorted({x['source_url'] for x in relevant}),
        'reason':'; '.join(f"{x['name']}: {x['regime']} through {x['observation_date']}" for x in relevant)+'. Price trends validate demand hypotheses; inventories and physical supply remain separate evidence gaps.'}
