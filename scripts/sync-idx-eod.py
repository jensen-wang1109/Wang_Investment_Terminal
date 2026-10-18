"""Manual and GitHub Actions entry point; never runs in the browser."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.idx_eod import run_eod,ENABLED_TICKERS

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--backfill',action='store_true');p.add_argument('--scheduled',action='store_true')
    p.add_argument('--symbols',nargs='+',choices=ENABLED_TICKERS,default=list(ENABLED_TICKERS))
    p.add_argument('--import-summary');p.add_argument('--fallback-file')
    p.add_argument('--trade-date');p.add_argument('--volume-unit',choices=['shares','lots'])
    args=p.parse_args();load_server_environment()
    results=[]
    for index,symbol in enumerate(dict.fromkeys(args.symbols)):
        if index:time.sleep(2)
        result=run_eod(ticker=symbol,backfill=args.backfill,scheduled=args.scheduled,summary_file=args.import_summary,trade_date=args.trade_date,volume_unit=args.volume_unit)
        if result['status'] in ('failed','blocked') and args.fallback_file:
            primary=result
            result=run_eod(ticker=symbol,summary_file=args.fallback_file,trade_date=args.trade_date,volume_unit=args.volume_unit)
            result['primary_run_id']=primary['run_id'];result['primary_status']=primary['status']
        results.append(result)
        print(json.dumps(result,indent=2),flush=True)
    raise SystemExit(0 if all(r['status'] in ('success','skipped') for r in results) else 2)
