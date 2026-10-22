import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.cloud import SupabaseStore
from services.research_api.sector_model import universe,load_prices
from services.research_api.ihsg_benchmark import benchmark_history
from services.research_api.sector_intelligence import config
from services.research_api.sector_rotation_backtest import validate_prices

if __name__=='__main__':
    load_server_environment();cloud=SupabaseStore();mapping=universe(cloud)
    report=validate_prices(load_prices(cloud,mapping,full=True,use_cache=True),mapping,benchmark_history(cloud),config())
    path=Path('.private/sector-model/rotation-validation.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report),flush=True)
