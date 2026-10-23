"""GitHub Actions/manual daily headline collection and database verification."""
import json,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.market_news import sync_market_news
from services.research_api.news_analyzer import generate_daily_analysis
if __name__=='__main__':
    load_server_environment()
    try:
        session='manual'
        if os.environ.get('GITHUB_EVENT_NAME')=='schedule':
            session='close' if os.environ.get('NEWS_SCHEDULE')=='15 10 * * 1-5' else 'morning'
            if session=='close':
                from datetime import datetime,timedelta,timezone
                from services.research_api.idx_calendar import session_dates
                today=datetime.now(timezone(timedelta(hours=7))).date().isoformat()
                if not session_dates(today,today):
                    print(json.dumps({'status':'skipped','reason':'IDX exchange holiday; morning brief remains scheduled daily'}));raise SystemExit(0)
        result=sync_market_news(trigger=os.environ.get('GITHUB_EVENT_NAME','manual'))
        print(json.dumps(result),flush=True)
        if result['database_verified'] and '--collect-only' not in sys.argv:
            analysis=generate_daily_analysis(session=session)
            print(json.dumps({'analyzer':analysis}),flush=True)
        raise SystemExit(0 if result['status'] in ('success','partial') and result['database_verified'] else 2)
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'reason':'News synchronization failed; check database configuration and source status'}),flush=True)
        raise SystemExit(2)
