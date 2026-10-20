"""GitHub Actions/manual daily headline collection and database verification."""
import json,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.market_news import sync_market_news
if __name__=='__main__':
    load_server_environment()
    try:
        result=sync_market_news(trigger=os.environ.get('GITHUB_EVENT_NAME','manual'))
        print(json.dumps(result),flush=True)
        raise SystemExit(0 if result['status'] in ('success','partial') and result['database_verified'] else 2)
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'reason':'News synchronization failed; check database configuration and source status'}),flush=True)
        raise SystemExit(2)
