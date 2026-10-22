"""Event-led research theses. Numerical model and headline evidence stay separate."""
import hashlib,json,re,uuid,threading
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from .cloud import SupabaseStore,CloudUnavailable
from .market_news import read,sync_market_news
from .news_analyzer import instant,topic_digest
from .feeds import approved_article
from .rights import ROOT
from .sector_model import universe,load_prices,feature_panel,train_model,predict,save_model,latest_model

THEMES=[
 {'id':'biodiesel','title':'Biodiesel & permintaan sawit','pattern':r'\bb50\b|biodiesel|mandatori b40',
  'industry':r'palm oil|agricultural|staple food',
  'thesis':'Jika realisasi blending biodiesel meningkatkan serapan bahan baku, produsen sawit dapat memperoleh dukungan permintaan. Dampak laba bergantung harga CPO, pungutan, biaya dan realisasi volume.',
  'risks':['Penundaan implementasi atau perubahan insentif/pendanaan.','Harga bahan baku naik dapat menekan industri pengguna; kenaikan harga saham mungkin sudah mendahului kabar.'],
  'confirm':['Realisasi volume biodiesel dan konsumsi CPO.','Tren harga CPO, margin dan volume produksi emiten.'],
  'reference':'https://esdm.go.id/id/media-center/arsip-berita/luncurkan-mandatori-b50-esdm-tegaskan-kesiapan-indonesia-perkuat-kedaulatan-energi'},
 {'id':'energy','title':'Energi, migas & rantai transportasi','pattern':r'krisis energi|harga minyak|pasokan minyak|selat hormuz|harga batu ?bara|ketahanan energi',
  'industry':r'oil & gas|oil, gas|coal|geothermal|renewable energy',
  'thesis':'Harga energi tinggi dapat mendukung produsen migas dan alternatif batu bara. Transportasi tanker perlu dikaji terpisah: tarif, utilisasi, charter dan risiko rute menentukan dampaknya; biaya bunker yang naik dapat menjadi tekanan.',
  'risks':['Harga minyak naik tidak otomatis menguntungkan semua perusahaan pelayaran.','Batu bara metalurgi berbeda dari thermal coal; substitusi energi tidak otomatis meningkatkan semua jenis batu bara.','Normalisasi pasokan, penurunan tarif angkut, volume rendah atau pembatasan ekspor dapat membalik tesis.'],
  'confirm':['Harga komoditas dan forward curve; volume serta biaya produksi.','Tarif charter/tanker dan bunker; kontrak spot versus jangka panjang.'],
  'reference':'https://www.iea.org/reports/oil-market-report-june-2026'},
 {'id':'ai_infrastructure','title':'Infrastruktur AI, listrik & logam','pattern':r'pusat data|data cent(?:er|re)|kecerdasan buatan|infrastruktur ai|\bai\b.*(?:tembaga|timah|aluminium|listrik)',
  'industry':r'data center|ai & cloud|computer hardware|electrical|it service|cyber|cooper|copper|\btin\b|aluminium',
  'thesis':'Capex AI dapat meningkatkan kebutuhan pusat data, listrik, jaringan dan sebagian material. Eksposur produsen tembaga, timah atau aluminium harus dibuktikan lewat produk, kontrak dan permintaan; label AI saja tidak cukup.',
  'risks':['Capex diumumkan belum sama dengan pendapatan yang terealisasi.','Keterbatasan pasokan listrik, valuasi mahal dan pembangunan berlebih dapat menekan return.'],
  'confirm':['Kontrak pelanggan, utilisasi pusat data dan belanja modal yang direalisasi.','Porsi pendapatan emiten dari rantai AI serta pasokan listrik dan margin.'],
  'reference':'https://www.iea.org/reports/energy-and-ai'},
 {'id':'monetary','title':'Suku bunga, rupiah & pembiayaan domestik','pattern':r'bi[- ]rate|suku bunga|the fed|rupiah|inflasi',
  'industry':r'bank|financing|property',
  'thesis':'Pelonggaran bunga dan stabilitas rupiah dapat membantu pembiayaan serta permintaan domestik. Untuk bank, arah margin bergantung kecepatan repricing kredit dan biaya dana; berita bunga harus dibaca bersama inflasi dan nilai tukar.',
  'risks':['Rupiah melemah atau inflasi meningkat dapat membatasi ruang pelonggaran.','Pertumbuhan kredit tidak otomatis memperbaiki kualitas aset dan margin.'],
  'confirm':['Keputusan BI/Fed, inflasi, nilai tukar dan yield obligasi.','Penyaluran kredit, biaya dana, NIM dan kualitas aset.'],
  'reference':'https://www.bi.go.id/id/fungsi-utama/moneter/default.aspx'}
]
ADVERSE=r'ditunda|penundaan|dibatalkan|pembatalan|gagal|krisis|kelangkaan|gangguan|merosot|anjlok'
SUPPORT=r'resmi|luncur|realisasi|implementasi|investasi|kontrak|bangun|naik|meningkat|menguat|pangkas|turunkan'
_job={'status':'idle'}
_job_lock=threading.Lock()

def monitor_job():
    with _job_lock:return dict(_job)

def start_monitor():
    with _job_lock:
        if _job['status']=='running':return dict(_job)
        _job.clear();_job.update(status='running',started_at=datetime.now(timezone.utc).isoformat())
    def work():
        try:
            result=run_monitor()
            with _job_lock:_job.update(status='success',result=result)
        except Exception:
            with _job_lock:_job.update(status='failed',error='Pembaruan gagal; laporan tersimpan sebelumnya dipertahankan.')
    threading.Thread(target=work,daemon=True).start()
    return monitor_job()

def news_inputs(cloud,now):
    rows=[];start=now-timedelta(days=7)
    for offset in range(0,5000,500):
        batch=read(cloud,'news_items?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'id,title,url,provider,topic,published_at,first_seen_at,quality_flag',
            'and':f'(published_at.gt.{start.isoformat()},published_at.lte.{now.isoformat()},first_seen_at.lte.{now.isoformat()})','order':'published_at.desc,id','limit':500,'offset':offset}))
        rows.extend(batch)
        if len(batch)<500:return rows
    raise CloudUnavailable('Seven-day news limit exceeded; prior theses retained')

def candidates_from_news(rows,mapping,previous,now):
    current={r['theme_id']:r for r in previous};result=[]
    for theme in THEMES:
        evidence=[];seen=set();provider_counts={}
        for a in rows:
            published=instant(a.get('published_at'));seen_at=instant(a.get('first_seen_at'))
            if not approved_article(a) or not published or not seen_at or not(now-timedelta(days=7)<published<=now) or seen_at>now or not re.search(theme['pattern'],a['title'],re.I):continue
            norm=re.sub(r'\W+',' ',a['title'].casefold()).strip()
            if norm in seen or provider_counts.get(a['provider'],0)>=4:continue
            seen.add(norm);provider_counts[a['provider']]=provider_counts.get(a['provider'],0)+1;evidence.append(a)
        prior=current.get(theme['id']);providers=sorted({a['provider'] for a in evidence})
        fresh=any(instant(a['published_at'])>=now-timedelta(hours=48) for a in evidence)
        if len(providers)<2 or not fresh:
            if prior:
                candidate={**prior['payload'],'status':'expired','rule_version':'sector-event-v2','evidence':evidence,'providers':providers,'updated_at':now.isoformat()}
                candidate['material_key']=hashlib.sha256((theme['id']+':expired:sector-event-v2').encode()).hexdigest();result.append(candidate)
            continue
        adverse=[a for a in evidence if re.search(ADVERSE,a['title'],re.I)];support=[a for a in evidence if re.search(SUPPORT,a['title'],re.I)]
        if theme['id']=='monetary':
            adverse=[a for a in evidence if re.search(r'rupiah[^.!?;]{0,30}(?:melemah|anjlok)|(?:suku bunga|bi[- ]rate|inflasi)[^.!?;]{0,30}(?:naik|meningkat)|(?:naikkan|menaikkan)[^.!?;]{0,20}(?:suku bunga|bi[- ]rate)',a['title'],re.I)]
            support=[a for a in evidence if re.search(r'rupiah[^.!?;]{0,30}menguat|(?:suku bunga|bi[- ]rate|inflasi)[^.!?;]{0,30}(?:turun|dipangkas)|(?:pangkas|turunkan)[^.!?;]{0,20}(?:suku bunga|bi[- ]rate)',a['title'],re.I)]
        # Energy crisis is a catalyst with two-sided effects, not universally bad.
        if theme['id']=='energy':adverse=[a for a in evidence if re.search(r'ditunda|dibatalkan|merosot|anjlok|gagal',a['title'],re.I)]
        status='contested' if adverse and support else 'risk' if adverse else 'supported' if support else 'watch'
        stage='execution' if any(not re.search(r'\?|diprediksi|diproyeksi|berpotensi|\bakan\b|rencana|berencana|menargetkan|menunggu',a['title'],re.I)
            and re.search(r'resmi|diluncurkan|terealisasi|realisasi|menandatangani|meneken kontrak|raih kontrak|mendapat kontrak',a['title'],re.I) for a in support) else 'developing'
        industries={}
        for ticker,info in mapping.items():
            if re.search(theme['industry'],info['industry'],re.I):industries.setdefault((info['sector'],info['industry']),[]).append(ticker)
        candidate={k:v for k,v in theme.items() if k not in ('pattern','industry')}
        candidate.update(status=status,stage=stage,rule_version='sector-event-v2',providers=providers,evidence=evidence,
            industries=[{'sector':s,'industry':i,'tickers':sorted(t)} for (s,i),t in industries.items()],
            updated_at=now.isoformat(),horizon='1-6 bulan: horizon riset, bukan target waktu pasti',research_only=True,
            evidence_strength='Penerbit beragam; independensi laporan dan isi artikel belum diverifikasi')
        # More headlines of the same stage/status do not create repeat notifications.
        candidate['material_key']=hashlib.sha256(json.dumps({'id':theme['id'],'status':status,'stage':stage,'rule_version':'sector-event-v2',
            'industries':[(s,i,sorted(t)) for (s,i),t in sorted(industries.items())]},sort_keys=True).encode()).hexdigest()
        result.append(candidate)
    return result

def save_macro_context(cloud):
    file=ROOT/'public/data/macro-history.json'
    if not file.exists():return
    dataset=json.loads(file.read_text(encoding='utf-8'));items=[]
    for series in dataset['series']:
        points=sorted((p for p in dataset['observations'] if p['seriesId']==series['id'] and p.get('value') is not None),key=lambda p:p['date'])
        if not points:continue
        last=points[-1];previous=points[-2] if len(points)>1 else None
        items.append({'id':series['id'],'name':series['label'],'value':last['value'],'previous':previous['value'] if previous else None,
            'date':last['date'],'previous_date':previous['date'] if previous else None,'frequency':series['frequency'],'unit':series['unit'],
            'source_url':series['sourceUrl'],'retrieved_at':last.get('retrievedAt'),'availability_verified':False})
    if not items:return
    prior=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'payload->>kind':'is.null','select':'payload','order':'generated_at.desc','limit':1}))
    combined={r['id']:r for r in prior[0]['payload']['items']} if prior else {}
    for item in items:
        if item['id'] not in combined or item['date']>=combined[item['id']]['date']:combined[item['id']]=item
    from .sector_intelligence import merge_macro_dataset
    prior_dataset=prior[0]['payload'].get('intelligence_dataset',{}) if prior else {}
    dataset=merge_macro_dataset(dataset,prior_dataset)
    payload={'items':list(combined.values()),'intelligence_dataset':dataset,'scope':'Snapshot resmi; frekuensi asli dipertahankan. Tidak menjadi fitur training tanpa vintage/availability historis.'}
    identity=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    cloud.request('sector_macro_context?on_conflict=owner_id,snapshot_id',[{'owner_id':cloud.owner,'snapshot_id':identity,'generated_at':dataset['generatedAt'],'payload':payload}],prefer='resolution=ignore-duplicates,return=representation')
    check=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'snapshot_id':'eq.'+identity,'select':'payload','limit':1}))
    if not check or check[0]['payload']!=payload:raise CloudUnavailable('Macro context readback mismatch')
    return dataset

def macro_snapshot(cloud,now):
    rows=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'payload->>kind':'is.null','select':'payload,generated_at','order':'generated_at.desc','limit':1}))
    if not rows:return {'items':[],'status':'unavailable','scope':'Angka makro resmi belum tersimpan. Berita tidak menggantikan data numerik.'}
    # Raw vintages live once in sector_macro_context, not every monitor run.
    result={k:v for k,v in rows[0]['payload'].items() if k!='intelligence_dataset'}
    for item in result['items']:
        age=(now.date()-datetime.fromisoformat(item['date']).date()).days
        limit={'annual':800,'quarterly':150,'monthly':70,'policy-event':180}.get(item['frequency'],7)
        item['stale']=age>limit;item['age_days']=age
    items={i['id']:i for i in result['items']};interpretations=[]
    for key,title,mechanism in [
        ('fed','Likuiditas global','Level bunga AS adalah konteks biaya modal; arah risk appetite perlu dikonfirmasi dengan yield dan berita terbaru.'),
        ('bi','Kebijakan domestik','Dampak pada kredit dan margin bank bergantung transmisi biaya dana, permintaan dan kualitas aset.'),
        ('usdidr','Rupiah & biaya valas','USD/IDR yang naik berarti rupiah melemah; periksa biaya impor dan utang valas. Nilai turun memberi efek sebaliknya.'),
        ('cpo','Permintaan & harga sawit','Benchmark bulanan berkaitan dengan pendapatan produsen dan biaya industri pengguna; realisasi biodiesel perlu diperiksa terpisah.'),
        ('brent','Energi global','Harga energi dapat membantu produsen tetapi menaikkan biaya konsumen energi dan bunker; dampak sektoral dua arah.')]:
        item=items.get(key)
        if item:
            value=f"{item['value']:g} {item['unit']}"
            prefix=f"Snapshot {item['date']}: {value}. "
            if item['stale']:prefix+='Data perlu diperbarui sebelum menilai kondisi terkini. '
            interpretations.append({'title':title,'summary':prefix+mechanism,'source_url':item['source_url']})
    return {**result,'status':'available','generated_at':rows[0]['generated_at'],'interpretations':interpretations}

def run_monitor(cloud=None,refresh_news=True,force_train=False):
    cloud=cloud or SupabaseStore();started=datetime.now(timezone.utc);run=str(uuid.uuid4())
    try:
        news_result=sync_market_news(cloud,trigger='sector_monitor') if refresh_news else None
        mapping=universe(cloud)
        # The old return-prediction model is an archive only. Rotation uses
        # deterministic price validation and the one shared trained topic model.
        rows=load_prices(cloud,mapping,full=False)
        if not rows:raise CloudUnavailable('No stored prices for industry validation')
        audit={'end':max(r['trade_date'] for r in rows)};forecasts=[]
        if force_train:
            from .macro_classifier import trained_classifier
            trained_classifier.cache_clear();trained_classifier()
        macro_dataset=save_macro_context(cloud)
        now=datetime.now(timezone.utc)
        previous=read(cloud,'sector_opportunity_state?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'theme_id,payload,material_key,revision','limit':20}))
        news=news_inputs(cloud,now);candidates=candidates_from_news(news,mapping,previous,now)
        # Legacy headline cards stay archived. Only the evidence-gated v2 engine
        # may publish new sector theses or notifications.
        from .sector_intelligence import run_intelligence
        from .shared_intelligence import refresh_shared_context,shared_snapshot
        refresh_shared_context(cloud)
        shared=shared_snapshot(cloud)['context']
        intelligence=run_intelligence(cloud,mapping,news,rows,now,dataset=macro_dataset,shared_context=shared)
        outcome={'changed':intelligence['published'],'notifications_created':intelligence['notifications_created']}
        context={'model_id':None,'active_model_id':shared['model']['training_hash'],'shared_analysis_id':shared['analysis_id'],'price_as_of':audit['end'],'predictions':forecasts,'macro':macro_snapshot(cloud,now),
            'news_context':topic_digest([a for a in news if approved_article(a)]),
            'news_count':len(news),'news_sync':news_result,'changes':outcome,'intelligence':intelligence,'research_only':True,
            'scope':'Satu model klasifikasi topik makro-sektoral dengan fakta primer dan price validation. Model prediksi harga lama hanya arsip; tidak dilatih atau dipakai untuk sinyal aktif.'}
        from .idx_calendar import session_dates,eligible_end
        local_now=now.astimezone(timezone(timedelta(hours=7)))
        eligible=session_dates((local_now.date()-timedelta(days=15)).isoformat(),eligible_end(local_now))
        context['expected_price_date']=eligible[-1] if eligible else None
        context['price_stale']=bool(eligible and audit['end']<eligible[-1])
        status='partial' if (news_result and news_result['status']!='success') or intelligence['macro_status']!='available' else 'success'
        row={'owner_id':cloud.owner,'run_id':run,'generated_at':now.isoformat(),'status':status,'payload':context}
        cloud.request('sector_monitor_runs',[row])
        check=read(cloud,'sector_monitor_runs?'+urlencode({'owner_id':'eq.'+cloud.owner,'run_id':'eq.'+run,'select':'payload','limit':1}))
        if not check or check[0]['payload']!=context:raise CloudUnavailable('Monitor context readback mismatch')
        return {'status':status,'database_verified':True,'run_id':run,'model_id':shared['model']['training_hash'],**outcome,'price_as_of':audit['end']}
    except Exception:
        cloud.request('sector_monitor_runs',[{'owner_id':cloud.owner,'run_id':run,'generated_at':datetime.now(timezone.utc).isoformat(),'status':'failed',
            'payload':{'error':'Sector research update failed; prior verified results retained'}}])
        raise

def sector_snapshot(cloud=None):
    cloud=cloud or SupabaseStore();filters={'owner_id':'eq.'+cloud.owner}
    states=read(cloud,'sector_opportunity_state?'+urlencode({**filters,'select':'theme_id,revision,updated_at,payload','order':'updated_at.desc','limit':20}))
    runs=read(cloud,'sector_monitor_runs?'+urlencode({**filters,'select':'generated_at,status','order':'generated_at.desc','limit':1}))
    success=read(cloud,'sector_monitor_runs?'+urlencode({**filters,'status':'in.(success,partial)','select':'generated_at,status,payload','order':'generated_at.desc','limit':1}))
    latest=success[0] if success else None
    if latest:latest['payload'].get('macro',{}).pop('intelligence_dataset',None)
    model=latest_model(cloud,latest['payload'].get('model_id') if latest else None)
    if model:model={k:v for k,v in model.items() if k!='current_predictions'};model['models']=[{k:v for k,v in m.items() if k!='parameters'} for m in model['models']]
    from .sector_intelligence import intelligence_snapshot
    return {'opportunities':states,'intelligence':intelligence_snapshot(cloud),'monitor':latest,'last_attempt':runs[0] if runs else None,'model':model,
        'schedule':'Pantau 07:30, 10:30, 13:30, 16:30 dan 19:30 WIB; publikasi/notifikasi hanya saat tesis berubah material.'}

def notification_snapshot(cloud=None):
    cloud=cloud or SupabaseStore()
    rows=read(cloud,'sector_notifications?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'id,theme_id,title,created_at,read_at,payload','order':'created_at.desc','limit':50}))
    unread=read(cloud,'sector_notifications?'+urlencode({'owner_id':'eq.'+cloud.owner,'read_at':'is.null','select':'id','limit':1000}))
    return {'notifications':rows,'unread':len(unread),'count_capped':len(unread)==1000}
