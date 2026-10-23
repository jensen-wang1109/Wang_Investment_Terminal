"""Evidence-linked, deterministic headline brief. No LLM or price forecasts.

Scores describe directional NEWS THEMES, not calibrated market probabilities.
Ambiguous headlines and commodity moves are kept out of broad-market scoring.
"""
import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from .cloud import SupabaseStore, CloudUnavailable
from .feeds import approved_article
from .market_news import read, SCHEDULE

VERSION='macro-headlines-shared-v3'
JAKARTA=timezone(timedelta(hours=7))
FIELDS='id,title,url,provider,topic,published_at,first_seen_at,quality_flag'
# A direction must follow the named subject in the SAME short clause.
UP=r'(?:menguat|naik|melesat|melonjak|meningkat|menghijau|ditutup hijau|rebound)'
DOWN=r'(?:melemah|turun|merosot|anjlok|terkoreksi|menurun|ditutup merah)'
RULES=[
 ('ihsg','Pasar saham Indonesia',r'ihsg',1,'Pergerakan IHSG menjadi konteks sentimen pasar saham domestik.'),
 ('rupiah','Rupiah',r'rupiah',1,'Penguatan rupiah dapat membantu biaya impor; pelemahan perlu dipantau untuk emiten berutang valas.'),
 ('global','Pasar saham global',r'(?:wall street|s&p 500|dow jones|nasdaq)',1,'Arah bursa AS dapat memengaruhi selera risiko; hubungan dengan IHSG tetap perlu dikonfirmasi.'),
 ('rates','Suku bunga',r'(?:bi[- ]rate|suku bunga(?: acuan)?|fed funds rate)',-1,'Penurunan bunga dapat mendukung pembiayaan dan properti; dampak pada margin bank bergantung repricing aset dan dana.'),
 ('growth','Pertumbuhan ekonomi',r'(?:pertumbuhan ekonomi|pdb)',1,'Pertumbuhan ekonomi berkaitan dengan permintaan domestik; periksa periode dan basis pembandingnya.'),
 ('oil','Harga minyak',r'(?:harga minyak(?: mentah)?)',0,'Kenaikan harga minyak dapat mendukung produsen migas dan menambah biaya bahan bakar transportasi; penurunan memberi efek sebaliknya.'),
 ('coal','Harga batu bara',r'harga (?:batu bara|batubara)',0,'Perubahan harga batu bara relevan bagi pendapatan produsen dan biaya energi pengguna; kontrak serta volume tetap menentukan.'),
 ('gold','Harga emas',r'harga emas',0,'Kenaikan harga emas dapat mendukung produsen emas, tetapi tidak otomatis berarti sentimen pasar saham luas positif.'),
 ('cpo','Harga CPO',r'harga (?:cpo|minyak sawit)',0,'Perubahan harga CPO relevan bagi produsen sawit dan biaya bahan baku industri pengguna.'),
 ('nickel','Harga nikel',r'harga nikel',0,'Perubahan harga nikel relevan bagi produsen logam; dampak laba perlu dikonfirmasi dengan biaya dan volume.')
]
UNCERTAIN=r'\?|\b(?:diprediksi|diproyeksi|diperkirakan|berpotensi|diprakirakan|proyeksi|prediksi|bakal|akan|berharap|target|jika|meski|walau|namun|tetapi|bukan|belum|tidak|gagal|batal|bantah|cegah)\b'
TOPIC_TERMS=[('IHSG & pasar saham',r'ihsg|bursa|pasar saham'),('rupiah',r'rupiah'),
 ('suku bunga & kebijakan moneter',r'suku bunga|bi[- ]rate|the fed|bank indonesia'),
 ('inflasi',r'inflasi'),('pertumbuhan & perdagangan',r'pertumbuhan|ekspor|impor|pdb|perdagangan'),
 ('emas',r'emas'),('energi',r'minyak|batu ?bara|migas|energi'),('logam',r'nikel|tembaga|timah'),
 ('sawit',r'cpo|sawit'),('kinerja & pendanaan emiten',r'laba|pendapatan|kinerja|obligasi|kredit|pendanaan'),
 ('aksi korporasi & keterbukaan',r'dividen|rapat umum|keterbukaan|pembelian kembali|laporan keuangan|rups')]

def topic_digest(articles):
    """Descriptive coverage of ALL eligible news, including unscored headlines."""
    result=[]
    for topic in dict.fromkeys(a.get('topic') or 'Berita lainnya' for a in articles):
        rows=[a for a in articles if (a.get('topic') or 'Berita lainnya')==topic]
        subjects=sorted(((name,sum(bool(re.search(pattern,a['title'].casefold())) for a in rows)) for name,pattern in TOPIC_TERMS),key=lambda pair:-pair[1])
        subjects=[name for name,count in subjects if count][:3]
        result.append({'topic':topic,'article_count':len(rows),
            'summary':f"{len(rows)} judul dari {len({a['provider'] for a in rows})} penerbit. "+('Sorotan judul: '+', '.join(subjects)+'.' if subjects else 'Perkembangan bisnis dan pengumuman emiten; dampak arah pasar belum disimpulkan.'),
            'evidence':rows[:5]})
    return result

def instant(value):
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError,TypeError,AttributeError):return None

def classification(title):
    text=title.casefold()
    if re.search(UNCERTAIN,text):return []
    if sum(bool(re.search(r'\b'+rule[2]+r'\b',text)) for rule in RULES)>1:return []
    found=[]
    for key,name,subject,polarity,impact in RULES:
        directions=set()
        for pattern,direction in ((UP,1),(DOWN,-1)):
            if re.search(r'\b'+subject+r'\b[^.!?;,:–—]{0,32}?\b'+pattern+r'\b',text):directions.add(direction)
        if len(directions)==1:
            direction=directions.pop()
            found.append((key,name,direction*polarity,impact,direction))
    # Multi-event headlines are too ambiguous for a directional theme assignment.
    return found if len(found)==1 else []

def build_report(articles,cutoff=None,knowledge_cutoff=None):
    cutoff=cutoff or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:raise ValueError('Timezone-aware cutoff required')
    cutoff=cutoff.astimezone(timezone.utc);start=cutoff-timedelta(hours=24)
    knowledge_cutoff=knowledge_cutoff or cutoff
    if knowledge_cutoff<cutoff:raise ValueError('Knowledge clock precedes publication cutoff')
    eligible=[];excluded=Counter();seen=set()
    for a in sorted(articles,key=lambda a:a.get('published_at') or '',reverse=True):
        if not approved_article(a):excluded['unapproved']+=1;continue
        published=instant(a.get('published_at'));known=instant(a.get('first_seen_at'))
        if not published:excluded['undated']+=1;continue
        if not known or known>knowledge_cutoff or published>cutoff or published<=start:excluded['outside_window']+=1;continue
        # Exact normalized titles across publishers count once, rather than RSS duplicates.
        normalized=re.sub(r'\W+',' ',a['title'].casefold()).strip()
        if normalized in seen:excluded['duplicate']+=1;continue
        seen.add(normalized);eligible.append({k:a.get(k) for k in FIELDS.split(',')})
    groups={};unclassified=[]
    for a in eligible:
        matches=classification(a['title'])
        if not matches:unclassified.append(a);continue
        key,name,value,impact,direction=matches[0]
        g=groups.setdefault(key,{'id':key,'theme':name,'impact':impact,'values':set(),'directions':set(),'evidence':[]})
        g['values'].add(value);g['directions'].add(direction);g['evidence'].append(a)
    factors=[]
    for g in groups.values():
        values=g.pop('values');directions=g.pop('directions')
        value=next(iter(values)) if len(values)==1 else 0
        direction='menguat/naik' if directions=={1} else 'melemah/turun' if directions=={-1} else 'berbeda arah antarjudul'
        g.update(sentiment='positive' if value>0 else 'negative' if value<0 else 'mixed',
                 summary=g['theme']+': judul berita melaporkan '+direction+'.',
                 evidence_count=len(g['evidence']))
        # Full lineage is retained. Only the UI collapses source lists.
        factors.append(g)
    positive=[g for g in factors if g['sentiment']=='positive'];negative=[g for g in factors if g['sentiment']=='negative']
    mixed=[g for g in factors if g['sentiment']=='mixed'];directional=len(positive)+len(negative)
    providers=sorted({a['provider'] for a in eligible})
    enough=directional>=3 and len(eligible)>=5 and len(providers)>=2
    score=round(100*(len(positive)-len(negative))/directional,1) if enough else None
    label='BULLISH' if score is not None and score>=20 else 'BEARISH' if score is not None and score<=-20 else 'CAMPURAN' if enough else 'BUKTI TERBATAS'
    summary=f"{len(eligible)} judul unik dari {len(providers)} penerbit: {len(positive)} tema mendukung, {len(negative)} tema menekan, dan {len(mixed)} tema campuran/sektoral."
    if not eligible:conclusion='Belum ada berita bertanggal yang memenuhi jendela analisis. Kesimpulan arah pasar belum dapat dibuat.'
    elif not enough:conclusion='Bukti arah pasar belum cukup beragam untuk menghitung skor. '+summary+' Pantau konfirmasi data pasar dan isi berita sumber.'
    else:conclusion=('Tema berita cenderung mendukung selera risiko. ' if score>=20 else 'Tema berita cenderung menekan selera risiko. ' if score<=-20 else 'Dukungan dan tekanan berita masih berimbang. ')+summary+' Ini ringkasan sentimen judul; arah maupun besaran perubahan IHSG belum diprediksi.'
    ihsg_rows=[a for a in eligible if re.search(r'ihsg|bursa efek indonesia|pasar saham indonesia',a['title'],re.I)]
    conclusion='Implikasi untuk IHSG / pasar saham Indonesia: '+conclusion
    identity={'version':VERSION,'start':start.isoformat(),'cutoff':cutoff.isoformat(),'knowledge_cutoff':knowledge_cutoff.isoformat(),'articles':eligible}
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'report_id':fingerprint,'report_date':cutoff.astimezone(JAKARTA).date().isoformat(),'generated_at':knowledge_cutoff.isoformat(),
            'knowledge_cutoff':knowledge_cutoff.isoformat(),'publication_cutoff':cutoff.isoformat(),
            'ihsg':{'summary':'IHSG selalu menjadi fokus analisis domestik. '+('Tersedia judul terkait IHSG; arah pre-open tetap perlu konfirmasi saat pembukaan.' if ihsg_rows else 'Belum ada judul IHSG langsung pada jendela ini; tidak dibuat kesimpulan arah pembukaan.'),'evidence':ihsg_rows[:8],'status':'headline_evidence' if ihsg_rows else 'insufficient_direct_evidence'},
            'timing_note':'Batas waktu berdasarkan timestamp publikasi sumber. Koleksi dapat selesai sesudah cutoff; waktu pertama terlihat dipertahankan. Bukan dataset point-in-time yang diketahui tepat pada pukul 08:00.',
            'window_start':start.isoformat(),'window_end':cutoff.isoformat(),'method':VERSION,'label':label,'score':score,
            'article_count':len(eligible),'providers':providers,'excluded':dict(excluded),'summary':summary,'conclusion':conclusion,
            'positive':positive,'negative':negative,'mixed':mixed,'unclassified':unclassified,
            'digests':topic_digest(eligible),
            'method_note':'Aturan judul berita, bukan model AI/ML. Skor = 100 × (tema positif − tema negatif) / tema berarah. Setiap tema memiliki satu suara, berapa pun jumlah artikelnya. Minimal 3 tema berarah, 5 judul unik, dan 2 penerbit. Skor bukan probabilitas, return, atau rekomendasi transaksi.',
            'scope_note':'Hanya judul dan metadata; isi artikel belum dibaca. Dampak sektoral adalah hipotesis bersyarat. Berita tanpa waktu publikasi dan judul ambigu tidak diberi skor.'}

def collect_inputs(cloud,cutoff,knowledge_cutoff=None):
    """Bounded pagination, with first-seen cutoff preventing retrospective lookahead."""
    start=cutoff-timedelta(hours=24);result=[]
    for offset in range(0,5000,500):
        page=read(cloud,'news_items?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':FIELDS,
            'and':f'(published_at.gt.{start.isoformat()},published_at.lte.{cutoff.isoformat()},first_seen_at.lte.{(knowledge_cutoff or cutoff).isoformat()})',
            'order':'published_at.desc,id','limit':500,'offset':offset}))
        result.extend(page)
        if len(page)<500:return result
    raise CloudUnavailable('News analysis input limit exceeded; report not replaced')

def generate_daily_analysis(cloud=None,cutoff=None,session='manual'):
    if cutoff is None:
        from .daily_intelligence import daily_report
        return daily_report(cloud,force=False)
    cloud=cloud or SupabaseStore();actual=datetime.now(timezone.utc);explicit=cutoff is not None
    if cutoff is None:
        local=actual.astimezone(JAKARTA)
        cutoff=local.replace(hour=17 if session=='close' else 8,minute=15 if session=='close' else 0,second=0,microsecond=0)
        if cutoff>local:cutoff-=timedelta(days=1)
        cutoff=cutoff.astimezone(timezone.utc)
    started=actual.isoformat();run=str(uuid.uuid4())
    try:
        knowledge=cutoff if explicit else actual
        report=build_report(collect_inputs(cloud,cutoff,knowledge),cutoff,knowledge)
        try:
            from .ihsg_benchmark import benchmark_history
            bars=benchmark_history(cloud,cutoff)
            last=bars[-1] if bars else None;previous=bars[-2] if len(bars)>1 else None
            report['ihsg']['benchmark']={'status':'available' if last else 'unavailable','symbol':'^JKSE',
                'close':last['close'] if last else None,'trade_date':last['trade_date'] if last else None,
                'daily_change_percent':100*(last['close']/previous['close']-1) if last and previous and previous['close'] else None,
                'source_url':'https://finance.yahoo.com/quote/%5EJKSE/history/'}
        except (CloudUnavailable,KeyError,TypeError):report['ihsg']['benchmark']={'status':'unavailable','symbol':'^JKSE'}
        if not explicit:
            from .shared_intelligence import refresh_shared_context
            shared=refresh_shared_context(cloud,publication_cutoff=cutoff)
            report['shared_analysis_id']=shared['analysis_id']
        report['session']=session
        report['report_id']=hashlib.sha256((report['report_id']+':'+session+json.dumps(report['ihsg'],sort_keys=True)+':'+report.get('shared_analysis_id','')).encode()).hexdigest()
        row={'owner_id':cloud.owner,'report_id':report['report_id'],'report_date':report['report_date'],
             'generated_at':report['generated_at'],'method':VERSION,'report':report}
        written=cloud.request('daily_market_analysis?on_conflict=owner_id,report_id',[row],prefer='resolution=ignore-duplicates,return=representation')
        checked=read(cloud,'daily_market_analysis?'+urlencode({'owner_id':'eq.'+cloud.owner,'report_id':'eq.'+report['report_id'],'select':'report','limit':1}))
        if not checked or checked[0]['report']!=report:raise CloudUnavailable('Analyzer report readback mismatch')
    except Exception:
        cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':run,'series_id':'analysis.daily','started_at':started,
            'finished_at':datetime.now(timezone.utc).isoformat(),'status':'failed','inserted_rows':0,'duplicate_rows':0,'error_code':'Analyzer failed; previous reports retained'}])
        raise
    cloud.request('ingestion_runs',[{'owner_id':cloud.owner,'run_id':run,'series_id':'analysis.daily','started_at':started,
        'finished_at':datetime.now(timezone.utc).isoformat(),'status':'success','inserted_rows':len(written or []),'duplicate_rows':0 if written else 1,'error_code':None}])
    return {'database_verified':True,'report_id':report['report_id'],'article_count':report['article_count'],'label':report['label']}

def analysis_snapshot(cloud=None,day=None,report_id=None):
    cloud=cloud or SupabaseStore()
    if day:
        from datetime import date
        day=date.fromisoformat(day).isoformat()
    filters={'owner_id':'eq.'+cloud.owner,'select':'report','order':'generated_at.desc,report_id','limit':1}
    if day:filters['report_date']='eq.'+day
    if report_id:
        if not re.fullmatch(r'[0-9a-f]{64}',report_id):raise ValueError('Invalid report version')
        filters['report_id']='eq.'+report_id
    rows=read(cloud,'daily_market_analysis?'+urlencode(filters))
    # Recent revisions, collapsed to one entry per Jakarta date for the picker.
    history=read(cloud,'daily_market_analysis?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'report_id,report_date,generated_at,session:report->>session','order':'generated_at.desc,report_id','limit':200}))
    days={}
    for r in history:days.setdefault(r['report_date'],r['generated_at'])
    logs=read(cloud,'ingestion_runs?'+urlencode({'owner_id':'eq.'+cloud.owner,'series_id':'eq.analysis.daily','select':'status,finished_at,error_code','order':'finished_at.desc','limit':1}))
    news_logs=read(cloud,'ingestion_runs?'+urlencode({'owner_id':'eq.'+cloud.owner,'series_id':'eq.news.market','select':'status,finished_at,error_code','order':'finished_at.desc','limit':1}))
    return {'report':rows[0]['report'] if rows else None,'history':[{'date':d,'generated_at':v} for d,v in days.items()],'versions':history,
            'last_attempt':logs[0] if logs else None,'news_sync':news_logs[0] if news_logs else None,'schedule':{'time':'19:00','timezone':'Asia/Jakarta','frequency':'daily','weekends':'short report using latest valid observations'},'cloud_persisted':True}
