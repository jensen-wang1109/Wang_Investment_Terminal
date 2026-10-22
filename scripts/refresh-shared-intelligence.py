import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.shared_intelligence import refresh_shared_context
if __name__=='__main__':
 load_server_environment();print(json.dumps(refresh_shared_context()),flush=True)
