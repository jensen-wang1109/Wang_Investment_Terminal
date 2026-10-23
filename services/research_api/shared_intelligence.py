"""One shared macro/sector context: trained topic model + dated facts + price evidence.

Classifier outputs are topics, not facts or return probabilities. Transmission
mechanisms are explicit conditional research assumptions, never learned causality.
"""
import copy,hashlib,html,json,re,uuid,threading
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from urllib.request import Request
from .rights import ROOT
from .cloud import SupabaseStore,CloudUnavailable
from .market_news import read
from .network import secure_open
from .news_analyzer import instant
from .macro_classifier import classify_texts

VERSION='shared-macro-sector-v2'
_job={'status':'idle'};_lock=threading.Lock()
LABELS={'global_equities':'Sentimen bursa global','commodities':'Komoditas & aktivitas industri','market_access':'Aksesibilitas & arus modal Indonesia','energy':'Energi & rantai pasok','global_monetary':'Kebijakan moneter global','domestic_monetary':'Moneter domestik & rupiah','biodiesel':'Sawit & kebijakan biodiesel','ai_capex':'AI, listrik & capex','domestic_growth':'Pertumbuhan & permintaan Indonesia'}

TRANSMISSIONS={
 'global_equities':{'macro':'Arah bursa global memberi konteks selera risiko. Korelasi tidak menjamin arah IHSG ketika risiko domestik, rupiah atau arus asing bergerak berbeda.',
   'chain':['Pergerakan indeks global','Selera risiko lintas pasar','Alokasi regional dan rupiah','Konfirmasi pada IHSG / EIDO'],
   'beneficiaries':[],'pressured':[{'industry':'Risk-sensitive equities','condition':'Tekanan risk-off baru relevan jika arus dana dan harga Indonesia ikut mengonfirmasi.'}],
   'confirm':['Return S&P, Dow, indeks Asia dan EIDO','Arus asing dan kekuatan relatif IHSG'],'invalidate':'Divergensi domestik membuat sentimen global tidak ditransmisikan ke IHSG.'},
 'commodities':{'macro':'Harga komoditas dapat mengubah terms of trade dan input industri. Arah manfaat bergantung komoditas spesifik, penyebab supply/demand, kurs, volume dan biaya; kenaikan harga tidak selalu berarti kelangkaan.',
   'chain':['Komoditas dan penyebab perubahan','Harga input / output serta perdagangan','Spread produsen vs pengguna','Konfirmasi industri dan pasar Indonesia'],
   'beneficiaries':[{'industry':'Relevant commodity producers','condition':'Komoditas dan exposure produk harus cocok; volume dan biaya tidak menghapus manfaat harga.'}],
   'pressured':[{'industry':'Commodity input users','condition':'Margin tertekan jika biaya naik tanpa pass-through atau hedge.'}],
   'confirm':['Benchmark dan satuan yang benar','Inventory, produksi, permintaan dan biaya','Relative strength beberapa representatif industri'],'invalidate':'Pasokan pulih, demand turun atau biaya naik lebih cepat dari output price.'},
 'market_access':{'macro':'Perubahan mandat indeks dapat mengubah permintaan investor pasif, likuiditas, premi risiko dan rupiah; besarnya arus keluar tidak dihitung tanpa data AUM serta bobot indeks.',
   'chain':['Aksesibilitas / klasifikasi indeks','Mandat dan alokasi investor asing','Likuiditas, rupiah dan premi risiko','IHSG serta biaya modal emiten'],
   'beneficiaries':[],'pressured':[{'industry':'Emiten dengan eksposur dana indeks asing','condition':'Keanggotaan indeks, free float dan porsi kepemilikan asing harus diverifikasi; risiko likuiditas dapat melintasi sektor.'}],
   'confirm':['Keputusan resmi MSCI dan implementasi reformasi','Arus asing, komposisi investor, free float dan likuiditas transaksi'],'invalidate':'Status resmi membaik atau bukti implementasi reformasi mengubah penilaian aksesibilitas.'},
 'energy':{'macro':'Jika kenaikan energi berasal dari gangguan pasokan, biaya transportasi dan input dapat naik, menekan daya beli dan menambah risiko inflasi. Kenaikan karena permintaan kuat memiliki konteks pertumbuhan berbeda.',
   'chain':['Sumber kejutan: supply atau demand','Harga energi dan biaya bunker / input','Inflasi, neraca perdagangan dan ruang BI','Divergensi produsen energi vs pengguna energi'],
   'beneficiaries':[{'industry':'Oil & Gas','condition':'Potensi ASP lebih tinggi jika volume produksi, biaya dan hedge mendukung.'},{'industry':'Oil & Gas Transportation (Tanker)','condition':'Perlu kenaikan ton-mile, tarif charter atau utilisasi; minyak naik saja tidak cukup. Biaya bunker dan risiko rute dapat menghapus manfaat.'},{'industry':'Oil, Gas & Coal Supports','condition':'Butuh realisasi capex pengeboran dan kontrak layanan. Lag order dapat melebihi horizon 1-6 bulan.'}],
   'pressured':[{'industry':'Air Transportation','condition':'Biaya bahan bakar naik jika tarif dan hedge tidak menutupinya.'},{'industry':'Manufacturing & Logistics','condition':'Dampak bergantung intensitas energi dan kemampuan meneruskan biaya.'}],
   'confirm':['Supply outage vs pertumbuhan demand','Tarif tanker, ton-mile, kontrak, bunker','Lifting, unit cost, hedge dan realisasi capex'],'invalidate':'Pasokan pulih, tarif angkut turun atau biaya naik lebih cepat dari harga jual.'},
 'global_monetary':{'macro':'Bunga AS, yield dan dolar memengaruhi likuiditas global, kurs dan biaya modal Indonesia. Arah kebijakan harus mengikuti keputusan resmi, bukan ekspektasi judul.',
   'chain':['Fed / yield / dolar','Likuiditas global dan risk appetite','Rupiah serta ruang kebijakan BI','Valuasi dan biaya pendanaan IHSG'],
   'beneficiaries':[{'industry':'Property & Financing','condition':'Pelonggaran global hanya membantu jika rupiah stabil dan bunga domestik ikut ditransmisikan.'}],
   'pressured':[{'industry':'Emiten berutang valas','condition':'Penguatan dolar dan funding cost tinggi dapat menambah beban tanpa hedge.'}],
   'confirm':['Keputusan bank sentral, inflasi AS dan Treasury','Dolar, rupiah dan transmisi biaya pendanaan'],'invalidate':'Inflasi atau yield berbalik sehingga skenario likuiditas tidak terwujud.'},
 'domestic_monetary':{'macro':'BI, inflasi, rupiah dan biaya dana menentukan ruang pertumbuhan kredit serta konsumsi. Pemangkasan bunga tidak otomatis memperbaiki NIM bank.',
   'chain':['BI Rate, inflasi dan rupiah','Repricing aset / dana','Permintaan kredit dan affordability','Konsumsi, investasi dan IHSG'],
   'beneficiaries':[{'industry':'Property','condition':'Affordability, presales dan akses KPR harus membaik.'},{'industry':'Financing','condition':'Spread pendanaan membaik tanpa lonjakan kredit bermasalah.'}],
   'pressured':[{'industry':'Bank','condition':'NIM dapat tertekan bila yield aset turun lebih cepat dari biaya dana; bukan seluruh bank otomatis negatif.'}],
   'confirm':['Keputusan BI dan realisasi inflasi','JISDOR, biaya dana, kredit dan kualitas aset'],'invalidate':'Tekanan kurs, inflasi atau kualitas kredit membatasi transmisi kebijakan.'},
 'biodiesel':{'macro':'Mandat biodiesel baru memengaruhi ekonomi fisik jika alokasi, pendanaan dan penyerapan feedstock benar-benar terealisasi. Rencana B50 bukan realisasi permintaan.',
   'chain':['Keputusan blending dan pendanaan','Realisasi volume FAME','Serapan CPO dan spread','Laba upstream vs biaya pengguna sawit'],
   'beneficiaries':[{'industry':'Palm Oil','condition':'Volume serapan, yield, biaya serta pungutan mendukung harga jual.'}],
   'pressured':[{'industry':'Downstream food producers','condition':'Feedstock mahal dapat menekan margin bila pass-through terbatas.'}],
   'confirm':['Keputusan ESDM, alokasi dan realisasi FAME','Produksi, stok, ekspor serta harga CPO'],'invalidate':'Implementasi tertunda atau peningkatan biaya/pungutan meniadakan manfaat.'},
 'ai_capex':{'macro':'Capex AI dapat membentuk permintaan pusat data, listrik dan konektivitas. Kontrak dan kapasitas listrik harus membuktikan materialitas; tidak semua produsen logam memperoleh manfaat.',
   'chain':['Capex AI yang dikomitmenkan','Pusat data, listrik dan grid','Order kabel / cooling / peralatan','Utilisasi, margin dan konversi kas'],
   'beneficiaries':[{'industry':'Data Center, AI & Cloud Infrastructure','condition':'Kontrak dan utilisasi terukur; kapasitas listrik tersedia.'},{'industry':'Electrical / copper supply chain','condition':'Produk dan kontrak terkait proyek harus terbukti; harga tembaga juga meningkatkan modal kerja.'}],
   'pressured':[{'industry':'Uncontracted data centers','condition':'Overcapacity dan beban capex dapat merusak return.'}],
   'confirm':['Kontrak, MW terpakai dan koneksi grid','Backlog, penggunaan material dan arus kas'],'invalidate':'Proyek dibatalkan, kapasitas berlebih atau harga saham mendahului realisasi.'},
 'domestic_growth':{'macro':'Pertumbuhan, konsumsi, manufaktur dan fiskal memengaruhi permintaan domestik. Perlu membedakan pertumbuhan nominal, riil, periode dan efek basis.',
   'chain':['PDB, konsumsi, PMI dan fiskal','Permintaan domestik','Volume penjualan / utilisasi','Margin dan pasar saham Indonesia'],
   'beneficiaries':[{'industry':'Consumer & Retail','condition':'Perbaikan daya beli dan volume harus dibuktikan; bukan sekadar kenaikan harga nominal.'}],
   'pressured':[{'industry':'Cyclical domestic demand','condition':'Permintaan yang lemah menekan volume bila biaya tetap tinggi.'}],
   'confirm':['Rilis BPS, PMI, konsumsi dan penjualan ritel','Kualitas fiskal, realisasi belanja dan perdagangan'],'invalidate':'Pertumbuhan konsumsi tidak berlanjut atau tekanan harga menghapus pendapatan riil.'}}

def refresh_official_facts(now=None):
    now=now or datetime.now(timezone.utc);facts=json.loads((ROOT/'config/official-macro-events.json').read_text(encoding='utf8'));result=[]
    for fact in facts:
        value=copy.deepcopy(fact)
        try:
            with secure_open(Request(fact['source_url'],headers={'User-Agent':'WangInvestmentResearch/1.0'}),timeout=20) as response:
                if not response.geturl().startswith(('https://msci.gcs-web.com/','https://ir.msci.com/')):raise ValueError('Untrusted fact redirect')
                body=response.read(2*1024*1024).decode('utf8','replace')
            text=' '.join(html.unescape(re.sub('<[^>]+>',' ',body)).split())
            if not all(marker.casefold() in text.casefold() for marker in fact['markers']):raise ValueError('Official announcement changed; review required')
            value.update(verification_status='primary_source_verified',verified_at=now.isoformat(),content_hash=hashlib.sha256(body.encode()).hexdigest())
        except Exception as error:
            verified=instant(fact['web_verified_at']);fresh=verified and now-verified<timedelta(hours=72)
            value.update(verification_status='web_reviewed_runtime_unavailable' if fresh else 'needs_review',verified_at=fact['web_verified_at'],refresh_error=type(error).__name__)
        value['state_is_final']=fact['event_state'] in ('final_decision','implemented') # This source describes consultation, never a completed downgrade.
        result.append(value)
    return result

def news_rows(cloud,now,knowledge=None):
    rows=[];start=now-timedelta(days=14)
    for offset in range(0,5000,500):
        batch=read(cloud,'news_items?'+urlencode({'owner_id':'eq.'+cloud.owner,'select':'id,title,url,provider,published_at,first_seen_at,topic',
            'and':f'(published_at.gt.{start.isoformat()},published_at.lte.{now.isoformat()},first_seen_at.lte.{(knowledge or now).isoformat()})','order':'published_at.desc','limit':500,'offset':offset}))
        rows.extend(batch)
        if len(batch)<500:break
    seen=set();unique=[]
    for article in rows:
        key=re.sub(r'\W+',' ',article['title'].casefold()).strip()
        if key not in seen:unique.append(article);seen.add(key)
    return unique

def price_context(cloud,now,cutoff=None):
    from .market_data import market_history
    result=[]
    for symbol in ['^JKSE','^GSPC','^DJI','EIDO','CL=F','BZ=F','GC=F','HG=F','ZW=F','IDR=X','DX-Y.NYB']:
        try:
            from .market_data import instrument
            from zoneinfo import ZoneInfo
            local=(cutoff or now).astimezone(ZoneInfo(instrument(symbol)['timezone']))
            close_time={'^JKSE':(16,45),'^GSPC':(16,30),'^DJI':(16,30),'EIDO':(16,30)}.get(symbol,(18,0))
            eligible=(local.date() if (local.hour,local.minute)>=close_time else local.date()-timedelta(days=1)).isoformat()
            if symbol=='^JKSE':
                from .idx_calendar import session_dates,eligible_end
                local_idx=(cutoff or now).astimezone(timezone(timedelta(hours=7)))
                sessions=session_dates((local_idx.date()-timedelta(days=15)).isoformat(),eligible_end(local_idx))
                eligible=sessions[-1] if sessions else eligible
            data=market_history(cloud,symbol);bars=[p for p in data['rows'] if instant(p['retrieved_at'])<=now and p['date']<=eligible]
            if not bars:continue
            last=bars[-1];previous=bars[-22] if len(bars)>21 else None
            from .indonesia_intelligence import market_features
            result.append({'symbol':symbol,'name':data['instrument']['label'],'value':last['value'],'unit':data['instrument']['unit'],'observation_date':last['date'],
                           'return_21':last['value']/previous['value']-1 if previous and previous['value']>0 else None,'source_url':data['instrument']['source_url'],'known_at':last['retrieved_at'],'features':market_features(bars,now,expected=eligible if symbol=='^JKSE' else None)})
        except CloudUnavailable:continue
    return result

def claim_state(text):
    text=text.casefold()
    if re.search(r'\b(?:batal|batalkan|membatalkan|cabut|mencabut)\b',text):return 'cancellation_claim'
    if re.search(r'\b(?:bukan|belum|tidak|bantah|membantah)\b',text):return 'negated_or_uncertain'
    if re.search(r'konsultasi|usul|propos|rencana|berpotensi|ancam|\bakan\b',text):return 'proposal_or_scenario'
    if re.search(r'(?:keputusan final|resmi|sudah|telah)[^.]{0,55}(?:downgrade|standalone|reklasifikasi|menurunkan)|(?:downgrade|reklasifikasi)[^.]{0,45}(?:resmi|final)',text):return 'final_decision_claim'
    return 'unverified_context'

def build_context(news,facts,prices,macro,model_report,classified,now):
    grouped={};counts={}
    for article,prediction in zip(news,classified):
        topic=prediction['topic'];counts[topic]=counts.get(topic,0)+1
        if topic in TRANSMISSIONS:grouped.setdefault(topic,[]).append({**article,'topic_score':prediction['topic_score']})
    active_facts=[f for f in facts if f['verification_status']!='needs_review' and instant(f['verified_at'])<=now and now-instant(f['verified_at'])<timedelta(hours=72)]
    if active_facts:grouped.setdefault('market_access',[])
    signals=[]
    for topic in TRANSMISSIONS:
        rows=grouped.get(topic)
        if rows is None:continue
        evidence=sorted(rows,key=lambda a:a.get('published_at') or '',reverse=True)[:5]
        fact=next((f for f in active_facts if topic=='market_access'),None)
        state='consultation_proposal' if fact else 'headline_context'
        if topic=='market_access' and any(claim_state(a['title']) in ('final_decision_claim','cancellation_claim') for a in evidence):
            state='conflicting_claims_need_primary_review'
        transmission=copy.deepcopy(TRANSMISSIONS[topic])
        related=[p for p in prices if p['symbol'] in ({'CL=F','BZ=F'} if topic=='energy' else {'^GSPC','^DJI','^JKSE','EIDO'} if topic=='global_equities' else {'GC=F','HG=F','ZW=F'} if topic=='commodities' else {'GC=F'} if topic=='global_monetary' else {'^JKSE','EIDO'} if topic=='market_access' else set())]
        for candidate in transmission['beneficiaries']:
            candidate['status']='conditional_research_hypothesis';candidate['eligible_recommendation']=False
        signals.append({'id':topic,'title':LABELS[topic],'state':state,'fact':fact,'evidence':evidence,'article_count':len(rows),
                        'classification_method':'trained_topic_classifier','numeric_evidence':related,**transmission})
    risks=[s for s in signals if s['id']=='market_access']
    context={'version':VERSION,'generated_at':now.isoformat(),'knowledge_cutoff':now.isoformat(),'model':model_report,'signals':signals,
             'official_facts':facts,'prices':prices,'macro':macro,'classified_counts':counts,'news_count':len(news),
             'macro_conclusion':('Risiko aksesibilitas pasar Indonesia perlu dipantau sesuai status pada fakta primer. ' if risks else '')+'Baca likuiditas global, rupiah, kebijakan domestik dan komoditas secara bersamaan. Potensi manfaat laba industri dapat berbeda arah dari risiko arus modal dan IHSG.',
             'sector_conclusion':'Beneficiary adalah hipotesis bersyarat. Konfirmasi relative strength, breadth, trend dan coverage pada evaluasi industri tetap diperlukan; tidak ada rekomendasi beli otomatis dari klasifikasi judul.',
             'method':'One trained topic classifier + source verification + conditional transmission graph. Price scoring validates rotation; facts are retrieved, not memorized by retraining.',
             'limitations':['Korpus pelatihan kecil dan berupa skenario edukasi; akurasi klasifikasi topik bukan akurasi prediksi pasar.','Judul media tidak memverifikasi isi artikel. Fakta primer ditampilkan terpisah dari interpretasi.','Tidak ada estimasi outflow, target IHSG atau probabilitas return tanpa data pendukung.','Timestamp koleksi aktual dipertahankan; konteks ini bukan backtest historis point-in-time.']}
    stable=copy.deepcopy(context);stable.pop('generated_at');stable.pop('knowledge_cutoff')
    context['analysis_id']=hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    return context

def refresh_shared_context(cloud=None,publication_cutoff=None):
    cloud=cloud or SupabaseStore();now=datetime.now(timezone.utc);cutoff=publication_cutoff or now;news=news_rows(cloud,cutoff,now);classified,model=classify_texts([a['title'] for a in news]);facts=[f for f in refresh_official_facts(now) if f['published_date']<=cutoff.date().isoformat()];prices=price_context(cloud,now,cutoff)
    from .sector_trends import macro_snapshot
    macro=macro_snapshot(cloud,now)
    if publication_cutoff:
        macro['items']=[i for i in macro.get('items',[]) if instant(i.get('retrieved_at')) and instant(i['retrieved_at'])<=cutoff]
        macro['interpretations']=[] # Do not retain prose derived from filtered future vintages.
    result=build_context(news,facts,prices,macro,model,classified,now)
    from .indonesia_intelligence import build_indonesia
    from .sector_intelligence import macro_analytics
    snapshots=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'payload->>kind':'is.null','select':'payload','order':'generated_at.desc','limit':1}))
    dataset=snapshots[0]['payload'].get('intelligence_dataset',{}) if snapshots else {}
    prior=read(cloud,'daily_market_analysis?'+urlencode({'owner_id':'eq.'+cloud.owner,'report_date':'lt.'+cutoff.astimezone(timezone(timedelta(hours=7))).date().isoformat(),'select':'report','order':'report_date.desc,generated_at.desc','limit':1}))
    previous=prior[0]['report'].get('brief',{}) if prior else {}
    result['indonesia']=build_indonesia(result,macro_analytics(dataset,cutoff if publication_cutoff else now),previous,now)
    result['publication_cutoff']=cutoff.isoformat()
    result['analysis_id']=hashlib.sha256(json.dumps({k:v for k,v in result.items() if k!='analysis_id'},sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    payload={'kind':'unified_intelligence','items':[],'context':result}
    cloud.request('sector_macro_context?on_conflict=owner_id,snapshot_id',[{'owner_id':cloud.owner,'snapshot_id':result['analysis_id'],'generated_at':now.isoformat(),'payload':payload}],prefer='resolution=ignore-duplicates,return=minimal')
    checked=read(cloud,'sector_macro_context?'+urlencode({'owner_id':'eq.'+cloud.owner,'snapshot_id':'eq.'+result['analysis_id'],'select':'payload','limit':1}))
    if not checked or checked[0]['payload']!=payload:raise CloudUnavailable('Shared intelligence readback mismatch')
    return {'analysis_id':result['analysis_id'],'database_verified':True,'signals':len(result['signals']),'model':model}

def shared_snapshot(cloud,as_of=None):
    query={'owner_id':'eq.'+cloud.owner,'payload->>kind':'eq.unified_intelligence','select':'payload','order':'generated_at.desc','limit':1}
    if as_of:
        stamp=instant(as_of)
        if not stamp:raise ValueError('Invalid context cutoff')
        query['payload->context->>publication_cutoff']='lte.'+stamp.astimezone(timezone.utc).isoformat()
    rows=read(cloud,'sector_macro_context?'+urlencode(query))
    return {'context':rows[0]['payload']['context'] if rows else None,'job':dict(_job),'storage':'Supabase'}

def start_shared_refresh():
    with _lock:
        if _job['status']=='running':return dict(_job)
        _job.clear();_job.update(status='running')
    def work():
        try:
            result=refresh_shared_context()
            with _lock:_job.update(status='success',result=result)
        except Exception:
            with _lock:_job.update(status='failed',error='Pembaruan konteks gagal; versi tersimpan dipertahankan.')
    threading.Thread(target=work,daemon=True).start();return dict(_job)
