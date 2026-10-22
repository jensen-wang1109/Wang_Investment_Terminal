"""A deduplicated FIFO for stock activation: EOD first, then company research.

Failures never undo activation or erase history. Cloud EOD/research logs remain
the durable record; local queue state reports interruption after a restart.
"""
import copy
import threading
from collections import deque
from .cloud import SupabaseStore
from .idx_eod import run_eod,EodStore
from .stock_enrichment import run_enrichment
from .infrastructure import atomic_json,read_json
from .repository import now_iso
from .rights import ROOT

FILE=ROOT/'.private/research/stock-onboarding.json'
_lock=threading.RLock()
_pending=deque()
_states={}
_thread=None

def onboarding_status():
    with _lock:
        states=copy.deepcopy(_states) if _states else read_json(FILE,{'stocks':{}}).get('stocks',{})
        alive=_thread and _thread.is_alive()
        if not alive:
            for state in states.values():
                if state['status'] in ('queued','running'):
                    state.update(status='interrupted',reason='Server dimulai ulang; gunakan Sinkron data untuk melanjutkan.')
        return {'stocks':states,'running':bool(alive)}

def sync_one(symbol,cloud=None,eod=run_eod,research=run_enrichment):
    cloud=cloud or SupabaseStore()
    if symbol not in cloud.tracked():return {'status':'skipped','reason':'Saham sudah nonaktif.'}
    # run_eod automatically backfills five years when no stored prices exist.
    price=eod(ticker=symbol,store=EodStore(cloud.env,cloud.transport))
    result={'prices':{k:price.get(k) for k in ('status','database_verified','verified_rows','records_inserted','records_updated','window_end','error_details')}}
    if not price.get('database_verified'):
        return {**result,'status':'failed','reason':'Harga belum berhasil diverifikasi. Histori sebelumnya dipertahankan.'}
    details=research([symbol],cloud=cloud)
    result['research']=details['results'][0]
    ok=result['research'].get('verified') and result['research']['status']=='success'
    return {**result,'status':'success' if ok else 'partial','reason':None if ok else 'Harga tersimpan; sebagian data riset belum tersedia. Lihat status modul.'}

def _save():atomic_json(FILE,{'stocks':_states})

def _work():
    global _thread
    while True:
        with _lock:
            if not _pending:
                _thread=None
                return
            symbol=_pending.popleft();_states[symbol].update(status='running',started_at=now_iso());_save()
        try:result=sync_one(symbol)
        except Exception as error:result={'status':'failed','reason':'Sinkronisasi gagal; histori valid tetap tersimpan. Coba ulang nanti.','error_type':type(error).__name__}
        with _lock:_states[symbol].update(result,finished_at=now_iso());_save()

def enqueue_stock(symbol):
    global _thread
    with _lock:
        if _states.get(symbol,{}).get('status') in ('queued','running') and _thread and _thread.is_alive():return copy.deepcopy(_states[symbol])
        _states[symbol]={'status':'queued','queued_at':now_iso()};_pending.append(symbol);_save()
        if not (_thread and _thread.is_alive()):
            _thread=threading.Thread(target=_work,daemon=True);_thread.start()
        return copy.deepcopy(_states[symbol])
