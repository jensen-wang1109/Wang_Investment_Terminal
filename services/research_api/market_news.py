"""Daily domestic market headlines; no article-body or image storage."""
import uuid
from datetime import datetime
from urllib.parse import urlencode
from .cloud import SupabaseStore,CloudUnavailable
from .feeds import FEEDS,GOOGLE_FEEDS,read_url,parse_feed,approved_article
from .providers import retry_transient
from .repository import now_iso

SPECS=FEEDS+GOOGLE_FEEDS
SCHEDULE={'time':'07:00','timezone':'Asia/Jakarta','days':'Setiap hari',
    'workflow_url':'https://github.com/jensen-wang1109/Wang_Investment_Terminal/actions/workflows/market-news.yml'}

def read(cloud,path):return retry_transient(lambda:cloud.request(path))

def news_snapshot(cloud=None):
    cloud=cloud or SupabaseStore()
    rows=read(cloud,'news_items?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'id,title,url,provider,feed_id,region,topic,published_at,first_seen_at,retrieved_at,quality_flag','order':'published_at.desc.nullslast,retrieved_at.desc','limit':300}))
    logs=read(cloud,'ingestion_runs?'+urlencode({'owner_id':'eq.'+cloud.owner,'series_id':'like.news.%','select':'series_id,status,started_at,finished_at,inserted_rows,error_code','order':'finished_at.desc','limit':100}))
    articles=[];seen=set()
    for row in rows:
        if not approved_article(row):continue
        key=(row['provider'],row['title'].casefold())
        if key in seen:continue
        articles.append(row);seen.add(key)
    sources=[]
    for spec in SPECS:
        entries=[r for r in logs if r['series_id']=='news.feed.'+spec['id']]
        latest=entries[0] if entries else {}
        last_success=next((r['finished_at'] for r in entries if r['status']=='available'),None)
        sources.append({'id':spec['id'],'provider':spec['provider'],'status':latest.get('status','not_synced'),
            'last_successful_fetch':last_success,'rows':latest.get('inserted_rows',0),'method':'Google News RSS' if spec.get('google_news') else 'RSS penerbit'})
    aggregate=[r for r in logs if r['series_id']=='news.market']
    latest=aggregate[0] if aggregate else {}
    success=next((r for r in aggregate if r['status'] in ('success','partial')),None)
    return {'articles':articles,'sources':sources,'cloud_persisted':True,'generated_at':success['finished_at'] if success else max((r['retrieved_at'] for r in articles),default=None),
        'last_attempt':latest.get('finished_at'),'status':latest.get('status','not_synced'),'schedule':SCHEDULE}

def by_ids(cloud,ids,fields):
    result=[]
    for offset in range(0,len(ids),50):
        result.extend(read(cloud,'news_items?'+urlencode({'owner_id':'eq.'+cloud.owner,'id':'in.('+','.join(ids[offset:offset+50])+')','select':fields,'limit':50})))
    return result

def sync_market_news(cloud=None,reader=read_url,trigger='manual'):
    cloud=cloud or SupabaseStore();started=now_iso();run=str(uuid.uuid4());fresh={};statuses=[]
    # Check actual database access before collecting. Never replace it with a new local store.
    read(cloud,'news_items?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'id','limit':1}))
    for spec in SPECS:
        timestamp=now_iso()
        try:
            rows=parse_feed(reader(spec['url']),spec,timestamp)
            fresh.update({r['id']:r for r in rows})
            state='available' if rows else 'empty';error=None
        except Exception:
            rows=[];state='failed';error='Source unavailable; saved articles retained'
        statuses.append({'series_id':'news.feed.'+spec['id'],'status':state,'started_at':timestamp,'finished_at':now_iso(),'inserted_rows':len(rows),'duplicate_rows':0,'error_code':error})
    rows=list(fresh.values());new_count=0;write_error=None;verified=False
    try:
        existing={r['id']:r for r in by_ids(cloud,list(fresh),'id,first_seen_at')}
        for row in rows:
            if row['id'] in existing:row['first_seen_at']=existing[row['id']]['first_seen_at']
            else:new_count+=1
        for offset in range(0,len(rows),100):cloud.save_news(rows[offset:offset+100])
        checked={r['id']:r for r in by_ids(cloud,list(fresh),'id,title,url,retrieved_at')}
        for row in rows:
            saved=checked.get(row['id'])
            if not saved or saved['title']!=row['title'] or saved['url']!=row['url'] or datetime.fromisoformat(saved['retrieved_at'])!=datetime.fromisoformat(row['retrieved_at']):
                raise CloudUnavailable('News write readback mismatch')
        verified=bool(rows)
    except CloudUnavailable:
        write_error='Cloud write/readback failed; previous articles retained'
    state='failed' if write_error or not rows else 'partial' if any(r['status']=='failed' for r in statuses) else 'success'
    finished=now_iso()
    statuses.append({'series_id':'news.market','status':state,'started_at':started,'finished_at':finished,'inserted_rows':new_count if verified else 0,'duplicate_rows':len(rows)-new_count if verified else 0,'error_code':write_error or ('No source articles returned' if not rows else None)})
    cloud.request('ingestion_runs',[{**r,'owner_id':cloud.owner,'run_id':run} for r in statuses])
    return {'status':state,'trigger':trigger,'started_at':started,'finished_at':finished,'fetched':len(rows),'new_articles':new_count if verified else 0,'database_verified':verified,
        'sources':[{'id':s['series_id'],'status':s['status'],'rows':s['inserted_rows']} for s in statuses[:-1]]}
