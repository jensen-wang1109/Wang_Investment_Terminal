"""Audit every active PBV from Yahoo valuation.Current; optionally collect financials."""
import argparse,copy,json,sys,time,uuid
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.cloud import SupabaseStore
from services.research_api.providers import retry_transient
from services.research_api.stock_details import normalize_statement
from services.research_api.stock_enrichment import access_status
from services.research_api.yahoo_valuation import apply_price_book

def audit(symbols=None,financials=False,sleep=time.sleep):
    import yfinance as yf
    load_server_environment();cloud=SupabaseStore();active=cloud.tracked();symbols=symbols or sorted(active,key=lambda s:(s!='SMDR.JK',s))
    if any(s not in active for s in symbols):raise ValueError('Only active watchlist symbols')
    report={'started_at':datetime.now(timezone.utc).isoformat(),'financials':financials,'results':[]};blocked=False
    output=Path('.private/research/financials-audit.json' if financials else '.private/research/pbv-audit.json');output.parent.mkdir(parents=True,exist_ok=True)
    for symbol in symbols:
        if blocked:report['results'].append({'symbol':symbol,'status':'skipped','reason':'Provider access restriction; circuit open'});continue
        stamp=datetime.now(timezone.utc).isoformat();result={'symbol':symbol,'status':'failed'}
        try:
            rows=cloud.request('current_stock_company_snapshots?'+urlencode({'owner_id':'eq.'+cloud.owner,'symbol':'eq.'+symbol,'select':'profile,metrics,basis,retrieved_at','limit':1}))
            if not rows:raise ValueError('Company snapshot unavailable')
            details=copy.deepcopy(rows[0]);details.update(retrieved_at=stamp,statements=[])
            ticker=yf.Ticker(symbol)
            if not financials:
                frame=retry_transient(lambda:ticker.valuation,sleep=sleep)
                apply_price_book(details,frame,stamp)
                details['profile'].setdefault('moduleStatus',{})['valuation']={'status':'available','last_success_at':stamp}
            else:
                failures=[]
                for kind,method in (('income',ticker.get_income_stmt),('balance',ticker.get_balance_sheet),('cashflow',ticker.get_cashflow)):
                    for frequency in ('yearly','quarterly'):
                        sleep(1)
                        try:
                            frame=retry_transient(lambda:method(freq=frequency,pretty=False),sleep=sleep)
                            details['statements']+=normalize_statement(frame,kind,frequency,details['profile'].get('financialCurrency'),datetime.now(timezone.utc))
                        except Exception as error:
                            if access_status(error) in (401,403,429):raise
                            failures.append(kind+'.'+frequency)
                if not details['statements']:raise ValueError('No financial statements returned')
                details['profile'].setdefault('moduleStatus',{})['financials']={'status':'partial' if failures else 'available','last_success_at':stamp,'failed_modules':failures,'source_limit':'Up to five years; only periods actually returned by Yahoo'}
            saved=cloud.save_stock_details(symbol,details)
            check=cloud.stock_details(symbol)
            if not financials:
                if check['company']['metrics']['priceToBook']!=details['metrics']['priceToBook']:raise ValueError('PBV readback mismatch')
                result.update(value=details['metrics']['priceToBook'],raw=details['profile']['metricProvenance']['priceToBook']['raw_info_value'])
            else:
                found={(r['statement_kind'],r['frequency'],r['period_end']):r for r in check['statements']}
                if any((r['statement_kind'],r['frequency'],r['period_end']) not in found or found[(r['statement_kind'],r['frequency'],r['period_end'])]['line_items']!=r['line_items'] for r in details['statements']):raise ValueError('Financial readback mismatch')
                result.update(periods=len(details['statements']),first=min(r['period_end'] for r in details['statements']),last=max(r['period_end'] for r in details['statements']))
            result.update(status='verified',database_verified=True)
        except Exception as error:
            blocked=access_status(error) in (401,403,429)
            result.update(error_type=type(error).__name__,reason='Source or database verification failed; prior valid snapshot retained')
        try:
            cloud.request('stock_research_sync_logs',[{'owner_id':cloud.owner,'run_id':str(uuid.uuid4()),'symbol':symbol,'status':'success' if result['status']=='verified' else 'failed','started_at':stamp,'finished_at':datetime.now(timezone.utc).isoformat(),'details':{'module':'financials' if financials else 'valuation','result':result}}])
        except Exception:
            result['log_warning']='Supabase sync log unavailable; local audit retained'
        report['results'].append(result);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result),flush=True);sleep(1.5)
    report['finished_at']=datetime.now(timezone.utc).isoformat();output.write_text(json.dumps(report,indent=2),encoding='utf8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--symbols',nargs='+');p.add_argument('--financials',action='store_true');args=p.parse_args()
    report=audit(args.symbols,args.financials)
    failed=[r for r in report['results'] if r['status']!='verified']
    print(json.dumps({'verified':len(report['results'])-len(failed),'unavailable_or_failed':len(failed),'report_file':'private audit log'}),flush=True)
    if any(r.get('error_type')!='ValueError' for r in failed) or any(r.get('log_warning') for r in report['results']):raise SystemExit(2)
