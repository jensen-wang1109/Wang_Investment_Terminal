"""Single shared daily pipeline; weekday and non-trading-day reports."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.daily_intelligence import daily_report
from services.research_api.cloud import SupabaseStore
from services.research_api.intelligence_memory import maintain_memory

if __name__=='__main__':
    load_server_environment();cloud=SupabaseStore()
    try:
        result=daily_report(cloud);print(json.dumps({'daily':result}),flush=True)
        print(json.dumps({'memory':maintain_memory(cloud)}),flush=True)
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'reason':'Unified pipeline failed; prior verified states retained'}),flush=True)
        raise SystemExit(2)
