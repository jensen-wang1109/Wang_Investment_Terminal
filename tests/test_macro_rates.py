import unittest
import copy,tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import date
from services.research_api.macro_rates import parse_adb,parse_fred,persist,parse_treasury,parse_h10,parse_policy
from services.research_api.cloud import CloudUnavailable

class MacroRateTests(unittest.TestCase):
    def test_treasury_parser_rejects_missing_tenor_and_future_values(self):
        xml='<feed xmlns="http://www.w3.org/2005/Atom" xmlns:d="urn:fixture"><entry><d:NEW_DATE>2026-10-22T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.65</d:BC_2YEAR><d:BC_10YEAR>4.96</d:BC_10YEAR></entry></feed>'
        self.assertEqual(parse_treasury(xml,date(2026,10,23))['ust10'],[('2026-10-22',4.96)])
        with self.assertRaises(ValueError):parse_treasury(xml,date(2026,10,21))
        with self.assertRaises(ValueError):parse_treasury(xml.replace('BC_2YEAR','WRONG'),date(2026,10,23))

    def test_weekly_release_keeps_daily_observation_dates_and_skips_ND(self):
        body='Release Date: October 19, 2026 '+''.join(f'<th id="a{i+3}">Oct. {12+i}</th>' for i in range(5))+'<tr><th>1) BROAD </th>'+''.join(f'<td headers="a{i+3} a1 r1">{v}</td>' for i,v in enumerate(['ND','121.4','122','121.5','121.4048']))+'</tr>'
        rows=parse_h10(body,date(2026,10,23));self.assertEqual(rows[-1],('2026-10-16',121.4048));self.assertEqual(len(rows),4)
        with self.assertRaises(ValueError):parse_h10(body.replace('BROAD','AFE'),date(2026,10,23))

    def test_fed_policy_date_is_not_replaced_with_today(self):
        body='<h4>2026</h4><table><tr><td>September 17</td><td>25</td><td>0</td><td>3.75-4.00</td></tr></table>'
        self.assertEqual(parse_policy(body,date(2026,10,23)),('2026-09-17',3.75,4.0))

    def test_publishers_are_retained_separately_and_conflict_cannot_confirm_regime(self):
        from services.research_api.macro_rates import macro_dataset
        from services.research_api.sector_intelligence import macro_analytics
        from datetime import datetime,timezone
        now=datetime(2026,10,23,12,tzinfo=timezone.utc)
        base=[{'observation_date':f'2026-10-{i:02}','value':4,'retrieved_at':'2026-10-23T00:00:00+00:00'} for i in range(1,23)]
        alternative=copy.deepcopy(base[-1:]);alternative[0]['value']=5
        class Cloud:
            owner='fixture'
            def request(self,*args):return []
            def history(self,sid):return copy.deepcopy(base if sid=='macro_daily_ust2' else alternative if sid=='macro_treasury_ust2' else [])
        with tempfile.TemporaryDirectory() as directory,patch('services.research_api.macro_rates.ROOT',Path(directory)):
            data=macro_dataset(Cloud())
        rows=[p for p in data['observations'] if p['seriesId']=='ust2']
        self.assertEqual(len(rows),22);self.assertTrue(rows[-1]['sourceConflict']);self.assertEqual(base[-1]['value'],4)
        feature=macro_analytics(data,now)[0];self.assertTrue(feature['source_conflict']);self.assertEqual(feature['regime'],'insufficient')
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
