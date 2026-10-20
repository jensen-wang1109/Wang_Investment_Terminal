import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.sector_trends import run_monitor

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--train',action='store_true');parser.add_argument('--skip-news',action='store_true');args=parser.parse_args()
    load_server_environment()
    try:print(json.dumps(run_monitor(refresh_news=not args.skip_news,force_train=args.train)),flush=True)
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'reason':'Prior verified sector reports retained; inspect database/source availability'}),flush=True)
        raise SystemExit(2)
