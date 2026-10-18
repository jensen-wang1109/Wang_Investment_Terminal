"""Owner-scoped server access. No privileged key is ever sent to the frontend."""
import json
import os
import re
import uuid
import hashlib
from urllib.parse import urlencode
from urllib.request import Request
from .network import secure_open
from urllib.error import HTTPError,URLError
from .repository import now_iso


class CloudUnavailable(Exception):
    def __init__(self,message,status_code=None):
        super().__init__(message)
        self.status_code=status_code


class SupabaseStore:
    def __init__(self, environ=None, transport=secure_open):
        self.env=os.environ if environ is None else environ
        self.transport=transport
        self.url=self.env.get('SUPABASE_URL','').rstrip('/')
        self.key=self.env.get('SUPABASE_SECRET_KEY') or self.env.get('SUPABASE_SERVICE_ROLE_KEY','')
        self.owner=self.env.get('WANG_SUPABASE_OWNER_ID','')
        self.last_success=None
        self.connected=False

    def configuration(self):
        missing=[]
        if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co',self.url) or 'YOUR_' in self.url.upper():missing.append('SUPABASE_URL')
        if not self.key or 'YOUR_' in self.key.upper():missing.append('SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_ROLE_KEY)')
        try:uuid.UUID(self.owner)
        except (ValueError,AttributeError):missing.append('WANG_SUPABASE_OWNER_ID')
        return {'configured':not missing,'missing':missing,'connected':self.connected and not missing,'last_successful_query':self.last_success}

    def request(self,path,body=None,prefer='return=representation'):
        if not self.configuration()['configured']:
            raise CloudUnavailable('Supabase configuration missing or contains placeholders')
        headers={'apikey':self.key,'Accept-Profile':'investment','Content-Profile':'investment','Content-Type':'application/json','Prefer':prefer}
        # New secret API keys are not JWTs. Only legacy JWT keys use Bearer auth.
        if not self.key.startswith('sb_secret_'):headers['Authorization']='Bearer '+self.key
        req=Request(self.url+'/rest/v1/'+path,data=None if body is None else json.dumps(body,allow_nan=False).encode(),headers=headers)
        try:
            with self.transport(req,timeout=20) as response:
                payload=response.read(10*1024*1024+1)
                if len(payload)>10*1024*1024:raise CloudUnavailable('Cloud response exceeds limit')
                result=json.loads(payload) if payload else None
            self.last_success=now_iso()
            self.connected=True
            return result
        except (HTTPError,URLError,ValueError,TimeoutError) as error:
            self.connected=False
            status=getattr(error,'code',None)
            if isinstance(error,(URLError,TimeoutError)) and not isinstance(error,HTTPError):status=503
            raise CloudUnavailable('Supabase request failed; check configuration, exposed schema, migrations and owner access',status) from None

    def status(self,verify=False):
        report=self.configuration()
        if verify and report['configured']:
            try:
                rows=self.request('sectors?'+urlencode({'owner_id':'eq.'+self.owner,'select':'id,code,name','limit':12}))
                report.update(connected=True,last_successful_query=self.last_success,sector_records=len(rows),taxonomy_complete=len(rows)==11)
            except CloudUnavailable as error:report['error']=str(error)
        return report

    def series(self):
        return self.request('data_series?'+urlencode({'owner_id':'eq.'+self.owner,'select':'*','order':'id'}))

    def history(self,series_id):
        rows=[]
        for offset in range(0,20000,1000):
            page=self.request('current_economic_observations?'+urlencode({'owner_id':'eq.'+self.owner,'series_id':'eq.'+series_id,'select':'*','order':'observation_date','limit':1000,'offset':offset}))
            rows.extend(page)
            if len(page)<1000:return rows
        raise CloudUnavailable('Series exceeds bounded historical response; narrower range required')

    def stock_snapshot(self,selected=None):
        companies=self.request('companies?'+urlencode({'owner_id':'eq.'+self.owner,'active':'eq.true','select':'id,symbol,name,company_watchlist_members!inner(active)','company_watchlist_members.active':'eq.true','order':'symbol','limit':201}))
        if len(companies)>200:raise CloudUnavailable('Research universe exceeds 200-stock cap')
        if selected and selected not in {c['symbol'] for c in companies}:raise ValueError('Ticker is not in the active research watchlist')
        ids=['yahoo_'+c['symbol'].lower().replace('.','_') for c in companies]
        latest=self.request('latest_economic_observations?'+urlencode({'owner_id':'eq.'+self.owner,'series_id':'in.('+','.join(ids)+')','select':'*'})) if ids else []
        profiles=self.request('company_research_profiles?'+urlencode({'owner_id':'eq.'+self.owner,'select':'company_id,industry_label,template_id,mapping_status,review_note,sectors(code,name)','limit':200}))
        try:
            vendor_rows=self.request('current_stock_company_snapshots?'+urlencode({'owner_id':'eq.'+self.owner,'select':'*','limit':200}))
            changes=self.request('stock_daily_changes?'+urlencode({'owner_id':'eq.'+self.owner,'series_id':'in.('+','.join(ids)+')','select':'*'})) if ids else []
            details=self.stock_details(selected) if selected else None
            detail_status='ready'
        except CloudUnavailable:
            vendor_rows=[];changes=[];details=None;detail_status='schema_or_query_unavailable'
        stocks=[]
        for company in companies:
            symbol=company['symbol'];sid='yahoo_'+symbol.lower().replace('.','_');point=next((r for r in latest if r['series_id']==sid),None)
            history=self.history(sid) if selected==symbol else []
            research=next((r for r in profiles if r['company_id']==company['id']),None)
            template=None
            if selected==symbol and research and research['template_id']:
                template_rows=self.request('industry_kpi_templates?'+urlencode({'owner_id':'eq.'+self.owner,'id':'eq.'+research['template_id'],'select':'industry_label,metrics,analyst_note,review_status,source_file'}))
                template=template_rows[0] if template_rows else None
            def value(row,key):return None if row.get(key) is None else float(row[key])
            stocks.append({'symbol':symbol,'status':'available' if point else 'unavailable','researchProfile':research,'kpiTemplate':template,'profile':{'name':company['name'],'currency':'IDR','exchange':'IDX','lastQuote':value(point,'value') if point else None,'quoteTime':None},'observationDate':point['observation_date'] if point else None,'retrievedAt':point['retrieved_at'] if point else None,'qualityFlag':point['quality_flag'] if point else None,'sourceUrl':'https://finance.yahoo.com/quote/'+symbol+'/','rawChecksum':point['revision_hash'] if point else None,'history':[{'date':r['observation_date'],'open':value(r,'open'),'high':value(r,'high'),'low':value(r,'low'),'close':value(r,'value'),'adjustedClose':value(r,'adjusted_close'),'volume':r.get('volume'),'periodStatus':'possibly-intraday' if 'intraday' in r['quality_flag'] else 'source_finality_unverified'} for r in history]})
            vendor=next((r for r in vendor_rows if r['symbol']==symbol),None)
            change=next((r for r in changes if r['series_id']==sid),{})
            stocks[-1].update(dailyChange=value(change,'price_change'),dailyChangePercent=value(change,'price_change_percent'),previousDate=change.get('previous_date'),details=details if selected==symbol else None)
            if vendor:
                stocks[-1]['profile'].update(name=vendor['profile'].get('longName') or vendor['profile'].get('shortName') or company['name'],businessSummary=vendor['profile'].get('longBusinessSummary'),vendorSector=vendor['profile'].get('sector'),vendorIndustry=vendor['profile'].get('industry'),financialCurrency=vendor['profile'].get('financialCurrency'),retrievedAt=vendor['retrieved_at'])
        # Serve the daily database table through the existing frontend contract.
        eod_status='unavailable'
        try:
            from .idx_eod import EodStore,ENABLED_TICKERS
            eod=EodStore(self.env,self.transport)
            for stock in stocks:
                symbol=stock['symbol']
                if symbol not in ENABLED_TICKERS:continue
                rows=eod.prices(symbol) if selected==symbol else self.request('stock_prices_daily?'+urlencode({'owner_id':'eq.'+self.owner,'ticker':'eq.'+symbol,'order':'trade_date.desc','limit':2}))[::-1]
                eod_status='ready'
                if not rows:continue
                last=rows[-1];previous=rows[-2] if len(rows)>1 else None
                if stock['observationDate'] and last['trade_date']<stock['observationDate']:continue
                stock.update(status='available',observationDate=last['trade_date'],retrievedAt=last['fetched_at'],qualityFlag='validated_eod',rawChecksum=last['row_hash'],priceSource=last['source'])
                stock['profile']['lastQuote']=float(last['close'])
                stock.update(previousDate=previous['trade_date'] if previous else None,dailyChange=float(last['close'])-float(previous['close']) if previous else None,dailyChangePercent=(float(last['close'])/float(previous['close'])-1)*100 if previous else None)
                if selected==symbol:stock['history']=[{'date':r['trade_date'],'open':float(r['open']),'high':float(r['high']),'low':float(r['low']),'close':float(r['close']),'adjustedClose':None if r['adjusted_close'] is None else float(r['adjusted_close']),'volume':r['volume'],'periodStatus':'eod'} for r in rows]
        except CloudUnavailable:pass
        return {'mode':'supabase','generatedAt':max((s['retrievedAt'] for s in stocks if s['retrievedAt']),default=now_iso()),'stocks':stocks,'eodSchema':eod_status,'extendedData':{'status':detail_status,'reason':'Vendor snapshots retain unknown publication dates. No generated fundamentals or point-in-time claims.'}}

    def tracked(self):
        rows=self.request('companies?'+urlencode({'owner_id':'eq.'+self.owner,'active':'eq.true','select':'symbol,company_watchlist_members!inner(active)','company_watchlist_members.active':'eq.true','limit':201}))
        return [r['symbol'] for r in rows]

    def latest_date(self,series_id):
        rows=self.request('current_economic_observations?'+urlencode({'owner_id':'eq.'+self.owner,'series_id':'eq.'+series_id,'select':'observation_date','order':'observation_date.desc','limit':1}))
        return rows[0]['observation_date'] if rows else None

    def detail_schema_ready(self):
        for table in ('stock_company_snapshots','stock_statement_snapshots','stock_action_snapshots'):
            self.request(table+'?'+urlencode({'owner_id':'eq.'+self.owner,'select':'symbol','limit':1}))
        return True

    def detail_state(self,symbol):
        rows=self.request('current_stock_company_snapshots?'+urlencode({'owner_id':'eq.'+self.owner,'symbol':'eq.'+symbol,'select':'retrieved_at','limit':1}))
        return rows[0] if rows else None

    def save_stock_details(self,symbol,details):
        base={'owner_id':self.owner,'symbol':symbol,'provider':'Yahoo Finance','retrieved_at':details['retrieved_at']}
        rows=[{**base,**statement} for statement in details['statements']]
        result={'statements':self._insert_revisions('stock_statement_snapshots',rows)}
        profile={**base,'observation_date':details['retrieved_at'][:10],'profile':details['profile'],'metrics':details['metrics'],'basis':details['basis'],'published_at':None,'available_at':None}
        result['profiles']=self._insert_revisions('stock_company_snapshots',[profile])
        return result

    def save_stock_actions(self,symbol,actions):
        return self._insert_revisions('stock_action_snapshots',[{**action,'symbol':symbol,'owner_id':self.owner,'provider':'Yahoo Finance'} for action in actions])

    def _insert_revisions(self,table,rows):
        for row in rows:
            identity={k:v for k,v in row.items() if k not in ('retrieved_at','revision_hash')}
            row['revision_hash']=hashlib.sha256(json.dumps(identity,sort_keys=True,allow_nan=False).encode()).hexdigest()
        count=0
        for offset in range(0,len(rows),250):
            count+=len(self.request(table,rows[offset:offset+250],prefer='resolution=ignore-duplicates,return=representation') or [])
        return {'inserted':count,'duplicates':len(rows)-count}

    def stock_details(self,symbol):
        filters={'owner_id':'eq.'+self.owner,'symbol':'eq.'+symbol,'select':'*','limit':1000}
        profile=self.request('current_stock_company_snapshots?'+urlencode({**filters,'limit':1}))
        statements=self.request('current_stock_statement_snapshots?'+urlencode({**filters,'order':'period_end.desc,statement_kind,frequency'}))
        actions=self.request('current_stock_action_snapshots?'+urlencode({**filters,'order':'event_date.desc'}))
        return {'status':'available' if profile else 'not_synced','company':profile[0] if profile else None,'statements':statements,'actions':actions,'source':'Yahoo Finance','point_in_time_ready':False}

    def kpi_library(self):
        sectors=self.request('sectors?'+urlencode({'owner_id':'eq.'+self.owner,'select':'id,code,name','order':'code'}))
        templates=self.request('industry_kpi_templates?'+urlencode({'owner_id':'eq.'+self.owner,'select':'id,sector_id,industry_label,metrics,analyst_note,source_file,source_sha256,review_status','order':'industry_label','limit':200}))
        profiles=self.request('company_research_profiles?'+urlencode({'owner_id':'eq.'+self.owner,'select':'industry_label,template_id,sector_id,mapping_status,review_note,companies!inner(symbol,active)','companies.active':'eq.true','limit':200}))
        return {'sectors':sectors,'templates':templates,'profiles':profiles,'training_ready':False,'measurement_status':'Definitions only; measured KPI values are not inferred'}

    def storage(self):
        return self.request('rpc/infrastructure_storage',{})

    def save_news(self,rows):
        if not rows:return []
        return self.request('news_items?on_conflict=owner_id,id',[{**row,'owner_id':self.owner} for row in rows],prefer='resolution=merge-duplicates,return=representation')

    def ingest(self,series,observations,run_id):
        return self.request('rpc/ingest_economic_batch',{'target_owner':self.owner,'series_record':series,'rows':observations,'run_identifier':run_id})
