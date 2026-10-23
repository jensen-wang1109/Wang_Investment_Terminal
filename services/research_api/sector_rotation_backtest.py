"""Chronological diagnostic of price factors only; no fabricated macro vintages."""
from datetime import datetime, timezone
from collections import defaultdict
import statistics
from .sector_rotation import industry_features, WEIGHTS

def validate_prices(prices,mapping,benchmark,cfg,round_trip_cost=.005):
    calendar=sorted({r['trade_date'] for r in benchmark});b={r['trade_date']:r['close'] for r in benchmark}
    groups=defaultdict(list);members=defaultdict(list)
    for symbol,m in mapping.items():members[m['industry']].append(symbol)
    for row in prices:
        if row['ticker'] in mapping:groups[mapping[row['ticker']]['industry']].append(row)
    outcomes=defaultdict(list);selected=defaultdict(list);by_ticker=defaultdict(dict)
    for r in prices:by_ticker[r['ticker']][r['trade_date']]=r['close']
    skipped_single=sum(len(s)<2 for s in members.values());predictions=[]
    # Non-tuned fixed weights, monthly decision dates, no future row in features.
    for index in range(252,len(calendar)-21,21):
        day=calendar[index];now=datetime.fromisoformat(day+'T12:00:00+00:00')
        past_b=[r for r in benchmark if r['trade_date']<=day]
        for industry,symbols in members.items():
            if len(symbols)<2:continue
            past=[r for r in groups[industry] if r['trade_date']<=day]
            features=industry_features(past,symbols,past_b,now,cfg)
            if features['coverage_confidence']['confidence']<cfg['minimum_data_quality']:continue
            values=features['values'];weight=sum(WEIGHTS[k] for k,v in values.items() if v is not None)
            if not weight or features['market'] is None:continue
            score=sum(v*WEIGHTS[k] for k,v in values.items() if v is not None)/weight
            chosen=score>=65 and not features['market']['overextended']
            for horizon in (21,63,126):
                if index+horizon>=len(calendar):continue
                end=calendar[index+horizon];returns=[]
                for symbol in symbols:
                    p=by_ticker[symbol]
                    if day in p and end in p and p[day]>0:returns.append(p[end]/p[day]-1)
                if len(returns)<2:continue
                excess=statistics.mean(returns)-(b[end]/b[day]-1)-round_trip_cost
                record={'date':day,'end':end,'industry':industry,'score':round(score,2),'excess':excess,'selected':chosen}
                outcomes[horizon].append(record)
                if chosen:selected[horizon].append(record)
    def summary(rows):
        return {'samples':len(rows),'decision_dates':len({r['date'] for r in rows}),
            'mean_excess_after_assumed_cost_pct':round(statistics.mean(r['excess'] for r in rows)*100,3) if rows else None,
            'positive_excess_rate_pct':round(sum(r['excess']>0 for r in rows)/len(rows)*100,2) if rows else None}
    return {'version':'rotation-technical-diagnostic-v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'status':'technical_only_not_combined_macro_validation','benchmark':'^JKSE',
        'weights':WEIGHTS,'technical_weight':sum(WEIGHTS[k] for k in ('relative','momentum','breadth','risk')),
        'round_trip_cost_assumption_pct':round_trip_cost*100,'selection_rule':'technical score >=65 and not overextended; fixed before this diagnostic',
        'range':[calendar[0],calendar[-1]] if calendar else [],'excluded_single_stock_industries':skipped_single,
        'horizons':{str(h):{'all_eligible':summary(outcomes[h]),'technical_shortlist':summary(selected[h])} for h in (21,63,126)},
        'combined_model_validated':False,'weights_optimized':False,
        'limitations':['No point-in-time macro release vintages: the full 100%-weight model has NOT been backtested.',
            'Current watchlist/industry membership creates selection and survivorship bias.',
            'Overlapping forward horizons and correlated industries mean samples are not independent.',
            'Close-price benchmark and stocks exclude dividends; execution and assumed costs are not verified.',
            'No probability forecast is made, so return-probability calibration/RMSE is not applicable.',
            'This historical diagnostic cannot establish future profitability or optimize the configured weights.']}
