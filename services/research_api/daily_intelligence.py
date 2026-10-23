"""One daily Indonesia brief, reusing the shared context and sector monitor."""
import copy,json,uuid,threading
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from .cloud import SupabaseStore,CloudUnavailable
from .market_news import read
from .indonesia_intelligence import VERSION,JAKARTA,digest

_lock=threading.Lock()

def daily_report(cloud=None,force=False,now=None,run_sector=True):
    cloud=cloud or SupabaseStore();now=now or datetime.now(timezone.utc);day=now.astimezone(JAKARTA).date().isoformat()
    session='daily' if now.astimezone(JAKARTA).hour>=19 else 'preview'
    with _lock:
        existing=read(cloud,'daily_market_analysis?'+urlencode({'owner_id':'eq.'+cloud.owner,'report_date':'eq.'+day,'method':'eq.'+VERSION,'report->>session':'eq.'+session,'select':'report','order':'generated_at.desc','limit':1}))
        if existing and not force:return {'database_verified':True,'report_id':existing[0]['report']['report_id'],'unchanged':True,'article_count':existing[0]['report'].get('article_count',0),'label':existing[0]['report']['brief']['equity_regime']['current']}
        run=str(uuid.uuid4());started=datetime.now(timezone.utc).isoformat()
        try:
            from .shared_intelligence import refresh_shared_context,shared_snapshot
            refresh_shared_context(cloud)
            context=shared_snapshot(cloud)['context'];brief=copy.deepcopy(context['indonesia']);sector=None
            if run_sector:
                from .sector_trends import run_monitor
                try:sector=run_monitor(cloud,refresh_news=False,shared_context=context)
                except CloudUnavailable:sector={'status':'failed','database_verified':False,'reason':'Sector validation unavailable; macro observations retained, no new industry recommendation.'}
                brief['ihsg']['watchlist_participation']=sector.get('watchlist_participation')
            from .idx_calendar import session_dates
            try:trading_day=bool(session_dates(day,day))
            except ValueError:trading_day=None
            brief['non_trading_day']=trading_day is False
            brief['calendar_status']='verified' if trading_day is not None else 'calendar review required'
            brief['report_mode']='short_non_trading_day' if trading_day is False else 'daily'
            # Preserve one linked state and the same impact relationships in both views.
            report={'method':VERSION,'report_date':day,'generated_at':datetime.now(timezone.utc).isoformat(),'publication_cutoff':context['publication_cutoff'],
                'knowledge_cutoff':context['knowledge_cutoff'],'window_start':(now-timedelta(days=1)).isoformat(),'window_end':context['publication_cutoff'],
                'session':session,'shared_analysis_id':context['analysis_id'],'brief':brief,'article_count':context['news_count'],
                'label':brief['equity_regime']['current'],'sector_evaluation':sector,'model':context['model'],
                'scope_note':'Indonesia-first; deterministic economic research plus one trained topic classifier. Return forecasting remains unvalidated.'}
            report['report_id']=digest({k:v for k,v in report.items() if k not in ('generated_at','sector_evaluation')})
            row={'owner_id':cloud.owner,'report_id':report['report_id'],'report_date':day,'generated_at':report['generated_at'],'method':VERSION,'report':report}
            written=cloud.request('daily_market_analysis?on_conflict=owner_id,report_id',[row],prefer='resolution=ignore-duplicates,return=representation')
            check=read(cloud,'daily_market_analysis?'+urlencode({'owner_id':'eq.'+cloud.owner,'report_id':'eq.'+report['report_id'],'select':'report','limit':1}))
            if not check or check[0]['report']!=report:raise CloudUnavailable('Daily intelligence readback mismatch')
            cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':run,'series_id':'analysis.daily','started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'status':'success','inserted_rows':len(written or []),'duplicate_rows':0 if written else 1,'error_code':None}])
            return {'database_verified':True,'report_id':report['report_id'],'article_count':report['article_count'],'label':report['label'],'sector':sector}
        except Exception:
            cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':run,'series_id':'analysis.daily','started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'status':'failed','inserted_rows':0,'duplicate_rows':0,'error_code':'Unified daily engine failed; previous reports retained'}])
            raise
