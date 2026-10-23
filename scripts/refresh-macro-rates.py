import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.macro_rates import refresh_rates
if __name__=='__main__':
    load_server_environment()
    result=refresh_rates();print(json.dumps(result),flush=True)
    raise SystemExit(0 if result['status']=='success' else 2)
