"""Synthetic unit fixtures only; these tests never access a production database."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from services.research_api.idx_eod import normalized_row,validate_rows,import_summary,run_eod,EodStore
from services.research_api.idx_calendar import session_dates,eligible_end
from services.research_api.contracts import PermissionDenied,DailyPrice
from services.research_api.cloud import CloudUnavailable

NOW=datetime.fromisoformat('2026-10-16T17:05:00+07:00')
FETCH='2026-10-16T10:05:00+00:00'
def row(day='2026-10-16',**overrides):
    return normalized_row(dict(trade_date=day,open=100,high=110,low=90,close=105,volume=1000,**overrides),'unit-test',FETCH,'synthetic')

class MemoryStore:
    def __init__(self):self.saved=[];self.events=[];self.commits=0
    def begin(self,r):self.events.append(('begin',dict(r)))
    def finish(self,r):self.events.append(('finish',dict(r)))
    def prices(self,*args):return self.saved
    def commit(self,r,rows,quality):
        self.commits+=1;self.saved=rows
        return dict(status='warning' if quality['missing_sessions'] else 'success',records_inserted=len(rows),records_updated=0,records_unchanged=0)

class EodTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p=patch('services.research_api.idx_eod.ROOT',Path(self.temp.name));p.start();self.addCleanup(p.stop)

    def test_calendar_excludes_official_holidays_and_weekends(self):
        self.assertEqual(len(session_dates('2026-01-01','2026-12-31')),239)
        self.assertEqual(session_dates('2026-03-18','2026-03-24'),[])
        self.assertEqual(session_dates('2026-10-17','2026-10-18'),[])
        with self.assertRaises(ValueError):session_dates('2026-12-30','2027-01-01')
        self.assertEqual(eligible_end(NOW.replace(hour=16)),'2026-10-15')

    def test_validation_rejects_corrupt_batches(self):
        for high in (80,float('nan'),float('inf')):
            with self.assertRaises(ValueError):normalized_row(dict(trade_date='2026-10-16',open=100,high=high,low=90,close=105,volume=1000),'test',FETCH,'fixture')
        with self.assertRaises(ValueError):validate_rows([row(),row()],'2026-10-16','2026-10-16')
        with self.assertRaises(ValueError):validate_rows([row('2026-10-17')],'2026-10-16','2026-10-18')
        with self.assertRaises(ValueError):validate_rows([],'2026-10-16','2026-10-16')
        self.assertEqual(validate_rows([row()],'2026-10-15','2026-10-18')['missing_sessions'],['2026-10-15'])

    def test_permission_failure_is_logged_without_source_call_or_write(self):
        store=MemoryStore()
        def deny(*a):raise PermissionDenied('Pending source review')
        result=run_eod(store=store,now=NOW,review=deny)
        self.assertEqual(result['status'],'blocked');self.assertFalse(result['source_request_attempted'])
        self.assertEqual(store.commits,0);self.assertEqual(store.events[-1][0],'finish')

    def test_holiday_skips_before_provider(self):
        store=MemoryStore()
        def forbidden(*a):self.fail('Source called on holiday')
        result=run_eod(store=store,scheduled=True,now=NOW.replace(month=12,day=31),review=forbidden)
        self.assertEqual(result['status'],'skipped');self.assertEqual(store.commits,0)

    def test_missing_sessions_are_reported_and_saved_rows_read_back(self):
        class Provider:
            def history(self,*a):return [DailyPrice('SMDR.JK','2026-10-16',100,110,90,105,None,1000,'IDR','yahoo',FETCH)]
        store=MemoryStore()
        result=run_eod(store=store,provider=Provider(),now=NOW,review=lambda *a:None)
        self.assertTrue(result['database_verified']);self.assertEqual(result['status'],'warning')
        self.assertGreater(len(result['quality']['missing_sessions']),1000)

    def test_bad_source_never_overwrites_history(self):
        class Provider:
            def history(self,*a):return [DailyPrice('SMDR.JK','2026-10-16',100,80,90,105,None,1000,'IDR','yahoo',FETCH)]
        store=MemoryStore();store.saved=[row('2026-10-15')]
        result=run_eod(store=store,provider=Provider(),now=NOW,review=lambda *a:None)
        self.assertEqual(result['status'],'failed');self.assertEqual(store.commits,0)
        self.assertEqual(store.saved[0]['trade_date'],'2026-10-15')

    def test_readback_failure_not_reported_as_success(self):
        class Store(MemoryStore):
            def prices(self,*args):return []
        file=Path(self.temp.name)/'sample.csv'
        file.write_text('ticker,trade_date,open,high,low,close,volume\nSMDR,2026-10-16,100,110,90,105,10\n')
        store=Store();result=run_eod(store=store,now=NOW,summary_file=file,volume_unit='shares')
        self.assertEqual(result['status'],'failed');self.assertEqual(result['records_inserted'],1)
        self.assertEqual(store.events[-1][1]['error_details']['phase'],'database_readback')

    def test_import_requires_units_and_preserves_null_adjusted_close(self):
        file=Path(self.temp.name)/'sample.csv'
        file.write_text('Stock Code,Open Price,Highest,Lowest,Close,Volume\nSMDR,100,110,90,105,10\n')
        with self.assertRaises(ValueError):import_summary(file,'SMDR.JK','2026-10-16')
        rows=import_summary(file,'SMDR.JK','2026-10-16','lots')
        self.assertEqual(rows[0]['volume'],1000);self.assertIsNone(rows[0]['adjusted_close'])

    def test_lost_commit_response_uses_database_log(self):
        store=EodStore({})
        with patch.object(store,'request',side_effect=CloudUnavailable('timeout',503)),patch.object(store,'logs',return_value=[dict(status='success',records_inserted=1,records_updated=0,records_unchanged=0)]):
            result=store.commit({'ticker':'SMDR.JK','run_id':'fixture'},[row()],{})
        self.assertEqual(result['records_inserted'],1)

if __name__=='__main__':unittest.main()
