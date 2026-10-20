"""Run the reproducible, experimental watchlist-sector backtest locally."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.cloud import SupabaseStore
from services.research_api.sector_model import universe,load_prices,train_model,save_model

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--save-cloud',action='store_true');parser.add_argument('--cached',action='store_true');args=parser.parse_args()
    load_server_environment();cloud=SupabaseStore();mapping=universe(cloud)
    print(json.dumps({'stage':'load_prices','stocks':len(mapping)}),flush=True)
    rows=load_prices(cloud,mapping,full=True,use_cache=args.cached)
    print(json.dumps({'stage':'purged_walk_forward','price_rows':len(rows)}),flush=True)
    report=train_model(rows,mapping)
    out=Path(__file__).resolve().parents[1]/'outputs/sector-model-evaluation.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    if args.save_cloud:print(json.dumps(save_model(cloud,report)),flush=True)
    print(json.dumps({'model_id':report['model_id'],'audit':{k:v for k,v in report['audit'].items() if k!='sectors'},
        'results':[{'months':m['approx_months'],'gate':m['statistical_gate_passed'],'metrics':m['metrics']} for m in report['models']]},ensure_ascii=False),flush=True)
