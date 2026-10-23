import unittest
from datetime import date
from services.research_api.macro_rates import parse_adb,parse_fred,persist
from services.research_api.cloud import CloudUnavailable

class MacroRateTests(unittest.TestCase):
    def test_dated_tenors_and_basis_points_are_not_confused(self):
        body='Close of<br/>October 21, 2026 <table>Govt. Bond Yields'+''.join(f'<tr><td>{n} Year</td><td>{v}</td><td>99.9</td></tr>' for n,v in [(2,6.925),(5,7.225),(10,7.421)])+'</table>Currencies'
        result=parse_adb(body,date(2026,10,23));self.assertEqual(result['sbn5'],('2026-10-21',7.225))
        with self.assertRaises(ValueError):parse_adb(body,date(2026,10,20))
        with self.assertRaises(ValueError):parse_adb(body.replace('Close of','Unknown date'),date(2026,10,23))
        with self.assertRaises(ValueError):parse_adb(body.replace('5 Year','7 Year'),date(2026,10,23))

    def test_fred_missing_days_are_not_filled_and_duplicate_dates_rejected(self):
        rows=parse_fred('observation_date,DGS10\n2026-10-20,4.25\n2026-10-21,.\n2026-10-24,4.30','DGS10',date(2026,10,23))
        self.assertEqual(rows,[('2026-10-20',4.25)])
        with self.assertRaises(ValueError):parse_fred('observation_date,DGS10\n2026-10-20,4\n2026-10-20,5','DGS10',date(2026,10,23))

    def test_dropped_write_cannot_be_marked_verified(self):
        from datetime import datetime,timezone
        class Cloud:
            def history(self,sid):return []
            def ingest(self,*args):return {'success':True}
        with self.assertRaises(CloudUnavailable):persist(Cloud(),'sbn2','SBN 2Y','%','https://example.org','fixture',[('2026-10-21',6.9)],datetime(2026,10,23,tzinfo=timezone.utc))
