"""Manual and GitHub Actions entry point; never runs in the browser."""
import argparse,json,sys,time,os,io,contextlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.idx_eod import run_eod,enabled_tickers,EodStore

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--backfill',action='store_true');p.add_argument('--scheduled',action='store_true')
    p.add_argument('--symbols',nargs='+',help='Defaults to the active Supabase watchlist')
    p.add_argument('--delay',type=float,default=2,help='Minimum seconds between symbols; must be at least 2')
    p.add_argument('--import-summary');p.add_argument('--fallback-file')
    p.add_argument('--trade-date');p.add_argument('--volume-unit',choices=['shares','lots'])
    args=p.parse_args();load_server_environment()
    store=EodStore();allowed=enabled_tickers(store);symbols=list(dict.fromkeys(args.symbols or allowed))
    if any(s not in allowed for s in symbols):p.error('Requested ticker is outside the active watchlist')
    if args.delay<2:p.error('Delay must be at least 2 seconds')
    results=[]
    for index,symbol in enumerate(symbols):
        if index:time.sleep(args.delay)
        # The watchlist is private; public Actions logs only receive aggregate progress.
        private_output=os.environ.get('GITHUB_ACTIONS')=='true'
        with contextlib.ExitStack() as capture:
            if private_output:
                capture.enter_context(contextlib.redirect_stdout(io.StringIO()))
                capture.enter_context(contextlib.redirect_stderr(io.StringIO()))
            result=run_eod(ticker=symbol,backfill=args.backfill,scheduled=args.scheduled,summary_file=args.import_summary,trade_date=args.trade_date,volume_unit=args.volume_unit,store=store,allowed_symbols=allowed)
        if result['status'] in ('failed','blocked') and args.fallback_file:
            primary=result
            result=run_eod(ticker=symbol,summary_file=args.fallback_file,trade_date=args.trade_date,volume_unit=args.volume_unit,store=store,allowed_symbols=allowed)
            result['primary_run_id']=primary['run_id'];result['primary_status']=primary['status']
        results.append(result)
        printable={'position':index+1,'total':len(symbols),'status':result['status'],'records_inserted':result['records_inserted'],'records_updated':result['records_updated']} if private_output else {k:v for k,v in result.items() if k!='quality'}|{'missing_sessions':len(result.get('quality',{}).get('missing_sessions',[]))}
        print(json.dumps(printable),flush=True)
    raise SystemExit(0 if all(r['status'] in ('success','warning','skipped') for r in results) else 2)
