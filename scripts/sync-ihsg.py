import json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.ihsg_benchmark import sync_benchmark
from services.research_api.cloud import SupabaseStore
if __name__=='__main__':
    load_server_environment();cloud=SupabaseStore();started=datetime.now(timezone.utc).isoformat()
    try:
        result=sync_benchmark(cloud);status='partial' if result.get('rejected') or result.get('missing_sessions') else 'success'
        print(json.dumps({'status':status,**result}),flush=True)
    except Exception as error:
        status='failed';result={'error_type':type(error).__name__};print(json.dumps({'status':status,**result}),flush=True)
    cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':str(uuid.uuid4()),'series_id':'market.ihsg',
        'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'status':status,
        'inserted_rows':int(result.get('inserted',0)),'duplicate_rows':0 if isinstance(result.get('unchanged'),bool) else int(result.get('unchanged',0)),'error_code':json.dumps(result) if status!='success' else None}])
    if status=='failed':raise SystemExit(2)
