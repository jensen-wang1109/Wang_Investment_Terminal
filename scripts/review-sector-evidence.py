"""Validate curated research assertions; dry-run by default. Never fetch input URLs."""
import argparse,json,sys,uuid
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.research_api.environment import load_server_environment
from services.research_api.cloud import SupabaseStore
from services.research_api.sector_intelligence import verified_assertion,GRAPH
from services.research_api.market_news import read

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('file',type=Path);parser.add_argument('--save-cloud',action='store_true');args=parser.parse_args()
    rows=json.loads(args.file.read_text(encoding='utf-8'));now=datetime.now(timezone.utc)
    if not isinstance(rows,list) or not rows or len(rows)>100:raise ValueError('Expected 1-100 evidence assertions')
    themes={s['id']:s for s in GRAPH}
    for row in rows:
        if not verified_assertion(row,now):raise ValueError('Missing / expired / invalid source-backed reviewed assertion')
        if row.get('event_id') not in themes:raise ValueError('Unknown event; add and review the causal hypothesis before scoring')
        if row.get('industry') not in [i['industry'] for i in themes[row['event_id']]['winners']]:raise ValueError('Industry is not a reviewed graph edge')
        if not row.get('reviewed_by') or not row.get('source_excerpt'):raise ValueError('Reviewer and source excerpt required; score must explain measurement basis')
    if not args.save_cloud:print(json.dumps({'validated':len(rows),'saved':False,'mode':'dry_run'}));return
    load_server_environment();cloud=SupabaseStore()
    for row in rows:
        identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,'wang-evidence:'+cloud.owner+':'+row['id']))
        cloud.request('sector_evidence_assertions?on_conflict=owner_id,id',[{'owner_id':cloud.owner,'id':identifier,'payload':row}],prefer='resolution=ignore-duplicates,return=representation')
        check=read(cloud,'sector_evidence_assertions?'+urlencode({'owner_id':'eq.'+cloud.owner,'id':'eq.'+identifier,'select':'payload','limit':1}))
        if not check or check[0]['payload']!=row:raise ValueError('Readback mismatch; revisions must use a new evidence ID')
    print(json.dumps({'validated':len(rows),'database_verified':True,'saved':len(rows)}))

if __name__=='__main__':main()
