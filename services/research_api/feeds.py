"""Bounded official RSS metadata reader. No article scraping, sentiment or forecasts."""
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse,urlencode
from urllib.request import Request
from .network import secure_open
from .providers import retry_transient
from .repository import now_iso

FEEDS=[{'id':'antara_'+section,'provider':'ANTARA','url':'https://www.antaranews.com/rss/'+section+'.xml','region':'Indonesia','evidence':'https://www.antaranews.com/rss','domains':['antaranews.com','www.antaranews.com']} for section in ('ekonomi','ekonomi-bursa','ekonomi-finansial')]
PUBLISHERS={'ANTARA':('antaranews.com',),'Bisnis.com':('bisnis.com',),'Kontan':('kontan.co.id',),'IDX':('idx.co.id','idx.id')}
TOPICS=('Bisnis & Market','Makro Indonesia','Makro Global','Komoditas','Keterbukaan IDX')
GOOGLE_FEEDS=[{'id':identifier,'provider':provider,'url':'https://news.google.com/rss/search?'+urlencode({'q':'site:'+domain+' (IHSG OR saham OR rupiah OR inflasi OR komoditas OR "The Fed" OR "keterbukaan informasi") when:7d','hl':'id','gl':'ID','ceid':'ID:id'}),'domains':list(PUBLISHERS[provider]),'region':'Indonesia','google_news':True}
    for identifier,provider,domain in [('google_bisnis','Bisnis.com','bisnis.com'),('google_kontan','Kontan','kontan.co.id'),('google_idx','IDX','idx.co.id')]]

GOOGLE_FEEDS += [{'id':'google_themes_'+provider.lower().replace('.','_'),'provider':provider,'url':'https://news.google.com/rss/search?'+urlencode({'q':'site:'+domain+' (B50 OR biodiesel OR \"krisis energi\" OR \"pusat data\" OR \"harga minyak\" OR \"infrastruktur AI\") when:7d','hl':'id','gl':'ID','ceid':'ID:id'}),'domains':list(PUBLISHERS[provider]),'region':'Indonesia','google_news':True} for provider,domain in [('Bisnis.com','bisnis.com'),('Kontan','kontan.co.id')]]


def google_news_url(url):
    try:
        p=urlparse(url)
        return p.scheme=='https' and p.hostname=='news.google.com' and p.port in (None,443) and not p.username and not p.password and p.path.startswith(('/rss/articles/','/articles/'))
    except (ValueError,TypeError):return False

def approved_article(row):
    return domestic_url(row.get('url',''),row.get('provider','')) or (row.get('quality_flag')=='google_news_rss_headline_only' and row.get('provider') in PUBLISHERS and google_news_url(row.get('url','')))


def domestic_url(url,provider):
    try:
        parsed=urlparse(url)
        return parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and any(parsed.hostname==domain or (parsed.hostname or '').endswith('.'+domain) for domain in PUBLISHERS.get(provider,()))
    except (ValueError,TypeError):return False


def topic_for(title):
    text=title.lower()
    if any(word in text for word in ('the fed','inflasi as','bank sentral as','ekonomi global','ekonomi china','ekonomi tiongkok','wall street','bank sentral eropa')):return 'Makro Global'
    if any(word in text for word in ('emas','minyak','batu bara','batubara','nikel','komoditas','cpo','timah')):return 'Komoditas'
    if any(word in text for word in ('inflasi','suku bunga','bank indonesia','pdb','devisa','neraca','rupiah','pertumbuhan ekonomi')):return 'Makro Indonesia'
    return 'Bisnis & Market'


def verified_headline(record,retrieved=None):
    """Import reviewed public search metadata; never fetch arbitrary input URLs."""
    url=record.get('url','');provider=record.get('provider','')
    if not domestic_url(url,provider):raise ValueError('Original domestic publisher URL required')
    title=re.sub(r'\s+',' ',record.get('title','')).strip()
    if not title or len(title)>300 or '<' in title:raise ValueError('Invalid headline')
    published=record.get('published_at')
    if published:
        instant=datetime.fromisoformat(published)
        if instant.tzinfo is None or instant>datetime.now(timezone.utc):raise ValueError('Invalid publication timestamp')
    retrieved=retrieved or now_iso();topic=record.get('topic',topic_for(title))
    if topic not in TOPICS:raise ValueError('Invalid news topic')
    return {'id':hashlib.sha256(url.encode()).hexdigest(),'title':title,'url':url,'provider':provider,'feed_id':provider.lower().replace('.','_')+'_reviewed_search','region':'Global' if topic=='Makro Global' else 'Indonesia','topic':topic,'published_at':published,'first_seen_at':retrieved,'retrieved_at':retrieved,'quality_flag':'assisted_web_search_headline_only','training_allowed':False}


def read_url(url,limit=2*1024*1024,transport=secure_open):
    # Only callers with static reviewed URLs use this helper; no user URL proxy.
    req=Request(url,headers={'User-Agent':'WangResearch/0.4 personal feed reader','Accept':'application/rss+xml,application/xml,text/csv;q=0.9,*/*;q=0.5'})
    def download():
        with transport(req,timeout=20) as response:
            body=response.read(limit+1)
            if len(body)>limit:raise ValueError('Source response exceeds limit')
            return body
    return retry_transient(download,attempts=2)


def parse_feed(body,spec,retrieved=None):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('XML declarations not allowed')
    root=ET.fromstring(body)
    if root.tag!='rss':raise ValueError('Expected RSS feed')
    retrieved=retrieved or now_iso(); rows=[]
    for item in root.findall('./channel/item')[:80]:
        url=(item.findtext('link') or '').strip(); parsed=urlparse(url)
        if spec.get('google_news'):
            source=item.find('source')
            if source is None or not domestic_url(source.get('url',''),spec['provider']) or not google_news_url(url):continue
        elif parsed.scheme!='https' or parsed.hostname not in spec['domains'] or parsed.username or parsed.password:continue
        title=re.sub(r'\s+',' ',item.findtext('title') or '').strip()[:300]
        if not title:continue
        raw=item.findtext('pubDate');published=None
        if raw:
            try:
                instant=parsedate_to_datetime(raw)
                if instant.tzinfo is not None and instant<=datetime.now(timezone.utc):published=instant.isoformat()
                elif instant.tzinfo is not None:continue
            except (ValueError,TypeError):pass
        if not spec.get('google_news') and not domestic_url(url,spec['provider']):continue
        topic=topic_for(title)
        if spec['provider']=='IDX' and any(term in title.lower() for term in ('keterbukaan','informasi kepada pemegang','rapat umum','dividen','pembelian kembali','laporan keuangan')):
            topic='Keterbukaan IDX'
        rows.append({'id':hashlib.sha256(url.encode()).hexdigest(),'title':title,'url':url,'provider':spec['provider'],'feed_id':spec['id'],'region':'Global' if topic=='Makro Global' else 'Indonesia','topic':topic,'published_at':published,'first_seen_at':retrieved,'retrieved_at':retrieved,'quality_flag':'google_news_rss_headline_only' if spec.get('google_news') else 'rss_headline_only','training_allowed':False})
    return rows


def refresh_news(previous=None,reader=read_url,reviewed=None):
    old={row['id']:row for row in (previous or {}).get('articles',[]) if domestic_url(row.get('url',''),row.get('provider',''))};statuses=[]
    if reviewed is None:
        import json
        from .rights import ROOT
        reviewed=json.loads((ROOT/'config/verified-domestic-headlines.json').read_text(encoding='utf-8'))
    for record in reviewed.get('articles',[]):
        row=verified_headline(record,reviewed['reviewed_at'])
        if row['id'] in old:row['first_seen_at']=old[row['id']]['first_seen_at']
        old[row['id']]=row
    for spec in FEEDS:
        try:
            timestamp=now_iso();rows=parse_feed(reader(spec['url']),spec,timestamp)
            for row in rows:
                if row['id'] in old:row['first_seen_at']=old[row['id']]['first_seen_at']
                old[row['id']]=row
            statuses.append({'id':spec['id'],'provider':spec['provider'],'status':'available' if rows else 'empty','last_successful_fetch':timestamp,'rows':len(rows),'source_url':spec['url']})
        except Exception:
            previous_status=next((s for s in (previous or {}).get('sources',[]) if s['id']==spec['id']),{})
            statuses.append({**previous_status,'id':spec['id'],'provider':spec['provider'],'status':'failed_cached_preserved','error':'Feed unavailable or invalid; no access-control workaround attempted'})
    for provider in ('Bisnis.com','Kontan','IDX'):
        statuses.append({'id':provider.lower(),'provider':provider,'status':'reviewed_search_manual_update','last_successful_fetch':reviewed.get('reviewed_at'),'rows':sum(r['provider']==provider for r in old.values())})
    return {'generated_at':now_iso(),'articles':sorted(old.values(),key=lambda r:r['published_at'] or '',reverse=True)[:200],'sources':statuses,'publisher_policy':'Indonesia only, including coverage of global macro','search_method':'RSS plus reviewed web-search metadata. Assistant browsing is not an embedded app API.','cloud_persisted':False,'probabilities_available':False}
