"""Versioned owner-scoped taxonomy configuration in the existing cloud context store.
Existing relational KPI templates remain read-only; user edits override the tree.
"""
import copy
import hashlib
import re
import threading
import uuid
from urllib.parse import urlencode
from .cloud import CloudUnavailable
from .repository import now_iso

_lock=threading.RLock()
KIND='stock_taxonomy_admin'

def name(value,label):
    if not isinstance(value,str) or not 1<=len(value.strip())<=160:raise ValueError(label+' wajib diisi (maksimal 160 karakter)')
    return ' '.join(value.split())

def read_overlay(cloud):
    rows=cloud.request('sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'payload->>kind':'eq.'+KIND,'select':'payload','order':'generated_at.desc','limit':1}))
    return copy.deepcopy(rows[0]['payload']['taxonomy']) if rows else {'sectors':[],'industries':[],'mappings':{}}

def save_overlay(cloud,state):
    identifier='taxonomy_'+str(uuid.uuid4());payload={'kind':KIND,'taxonomy':state}
    cloud.request('sector_macro_context',[{'owner_id':cloud.owner,'snapshot_id':identifier,'generated_at':now_iso(),'payload':payload}])
    rows=cloud.request('sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'snapshot_id':'eq.'+identifier,'select':'payload','limit':1}))
    if not rows or rows[0]['payload']!=payload:raise CloudUnavailable('Pemetaan belum terverifikasi di database')

def apply_overlay(cloud,tree):
    state=read_overlay(cloud);sectors=tree['sectors'];known={s['id']:s for s in sectors}
    for s in state['sectors']:
        if s['id'] not in known:
            sector={**s,'industries':[],'stock_count':0};sectors.append(sector);known[s['id']]=sector
    for i in state['industries']:
        sector=known.get(i['sector_id'])
        if sector and not any(x['id']==i['id'] for x in sector['industries']):sector['industries'].append({**i,'stocks':[],'metrics':[],'note':'User-defined industry'})
    stocks={x['symbol']:x for s in sectors for i in s['industries'] for x in i['stocks']}
    stocks.update({x['symbol']:x for x in tree['unmapped']})
    for symbol,m in state['mappings'].items():
        sector=known.get(m['sector_id']);industry=next((i for i in sector['industries'] if i['id']==m['industry_id']),None) if sector else None
        if symbol not in stocks or not industry:continue
        for s in sectors:
            for i in s['industries']:i['stocks']=[x for x in i['stocks'] if x['symbol']!=symbol]
        industry['stocks'].append(stocks[symbol]);tree['unmapped']=[x for x in tree['unmapped'] if x['symbol']!=symbol]
    for s in sectors:
        s['industries'].sort(key=lambda i:i['name'].casefold());s['stock_count']=sum(len(i['stocks']) for i in s['industries'])
    tree['industry_count']=sum(len(s['industries']) for s in sectors)
    return tree

def taxonomy(cloud):
    return {'sectors':[{k:s[k] for k in ('id','code','name','industries')} for s in cloud.sector_tree()['sectors']]}

def create_sector(cloud,payload):
    label=name(payload.get('name'),'Nama sektor');code=name(payload.get('code'),'Kode sektor').upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9_-]{1,29}',code):raise ValueError('Kode sektor: 2–30 huruf, angka, _ atau -')
    with _lock:
        sectors=taxonomy(cloud)['sectors']
        existing=next((s for s in sectors if s['code']==code or s['name'].casefold()==label.casefold()),None)
        if existing:return {'sector':existing,'verified':True,'existing':True}
        identifier=-int(hashlib.sha256(code.encode()).hexdigest()[:12],16)
        row={'id':identifier,'stable_id':'user_sector_'+code,'code':code,'name':label,'source':'Manual stock mapping'}
        state=read_overlay(cloud);state['sectors'].append(row);save_overlay(cloud,state)
        return {'sector':{**row,'industries':[]},'verified':True}

def create_industry(cloud,payload):
    label=name(payload.get('name'),'Nama industri');sid=payload.get('sector_id')
    with _lock:
        sector=next((s for s in taxonomy(cloud)['sectors'] if s['id']==sid),None)
        if not sector:raise ValueError('Pilih sektor yang tersedia')
        existing=next((i for i in sector['industries'] if i['name'].casefold()==label.casefold()),None)
        if existing:return {'industry':existing,'verified':True,'existing':True}
        identifier='custom_'+hashlib.sha256((str(sid)+':'+label.casefold()).encode()).hexdigest()[:24]
        row={'id':identifier,'sector_id':sid,'name':label}
        state=read_overlay(cloud);state['industries'].append(row);save_overlay(cloud,state)
        return {'industry':row,'verified':True}

def save_mapping(cloud,payload):
    symbol=name(payload.get('symbol'),'Ticker').upper();symbol=symbol if symbol.endswith('.JK') else symbol+'.JK'
    with _lock:
        sector=next((s for s in taxonomy(cloud)['sectors'] if s['id']==payload.get('sector_id')),None)
        industry=next((i for i in sector['industries'] if i['id']==payload.get('industry_id')),None) if sector else None
        if not industry:raise ValueError('Industri harus berada di sektor yang dipilih')
        companies=cloud.request('companies?'+urlencode({'owner_id':'eq.'+cloud.owner,'symbol':'eq.'+symbol,'select':'id','limit':1}))
        if not companies:raise ValueError('Tambahkan saham sebelum menyimpan pemetaan')
        row={'sector_id':sector['id'],'industry_id':industry['id'],'industry_label':industry['name'],'updated_at':now_iso()}
        state=read_overlay(cloud);state['mappings'][symbol]=row;save_overlay(cloud,state)
        return {'verified':True,'symbol':symbol,**row}
