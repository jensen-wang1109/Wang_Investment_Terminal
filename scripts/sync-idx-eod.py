"""Manual and GitHub Actions entry point; never runs in the browser."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.idx_eod import run_eod

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--backfill',action='store_true');p.add_argument('--scheduled',action='store_true')
    p.add_argument('--import-summary');p.add_argument('--fallback-file')
    p.add_argument('--trade-date');p.add_argument('--volume-unit',choices=['shares','lots'])
    args=p.parse_args();load_server_environment()
    result=run_eod(backfill=args.backfill,scheduled=args.scheduled,summary_file=args.import_summary,trade_date=args.trade_date,volume_unit=args.volume_unit)
    if result['status'] in ('failed','blocked') and args.fallback_file:
        primary=result
        result=run_eod(summary_file=args.fallback_file,trade_date=args.trade_date,volume_unit=args.volume_unit)
        result['primary_run_id']=primary['run_id'];result['primary_status']=primary['status']
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['status'] in ('success','skipped') else 2)
