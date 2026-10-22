import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.market_data import sync_market_history,sync_commodities
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--symbols',nargs='*');p.add_argument('--skip-history',action='store_true');p.add_argument('--skip-commodities',action='store_true');p.add_argument('--force',action='store_true');a=p.parse_args();load_server_environment();failed=False
 if not a.skip_commodities:
  try:
   result=sync_commodities();print(json.dumps({'commodities':result}),flush=True);failed=result['status']!='success'
  except Exception as e:
   failed=True;print(json.dumps({'commodities':{'status':'failed','error_type':type(e).__name__}}),flush=True)
 if not a.skip_history:
  result=sync_market_history(symbols=a.symbols,force=a.force);print(json.dumps(result),flush=True)
  if result['status']!='success':failed=True
 if failed:sys.exit(2)
