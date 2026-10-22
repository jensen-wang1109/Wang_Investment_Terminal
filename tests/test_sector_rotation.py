import copy,unittest
from datetime import datetime,timedelta,timezone
from services.research_api.sector_rotation import combine_factors,industry_features,stock_features
from services.research_api.sector_intelligence import config,score_industry,GRAPH
from services.research_api.news_impacts import impacts
from services.research_api.yahoo_valuation import apply_price_book,protect_unverified_pbv
from services.research_api.stock_details import normalize_statement
import pandas as pd

NOW=datetime(2026,10,21,12,tzinfo=timezone.utc)
def bars(symbol='A',count=300):
    return [{'ticker':symbol,'trade_date':(NOW-timedelta(days=count-1-i)).date().isoformat(),
        'close':100*1.001**i,'volume':1000} for i in range(count)]

class RotationTests(unittest.TestCase):
    def test_missing_metrics_are_excluded_not_neutral_or_zero(self):
        score,weight=combine_factors({'a':{'weight':25,'value':80},'b':{'weight':75,'value':None}})
        self.assertEqual((score,weight),(80,25));self.assertEqual(combine_factors({'x':{'weight':100,'value':None}}),(None,0))

    def test_actual_ihsg_comparison_and_no_future_lookahead(self):
        price=bars();benchmark=bars('^JKSE')
        f=stock_features(price,benchmark,NOW,config());self.assertAlmostEqual(f['relative'][126],0)
        future={'trade_date':(NOW+timedelta(days=1)).date().isoformat(),'close':1e9,'ticker':'A','volume':1}
        self.assertEqual(f,stock_features(price+[future],benchmark+[future],NOW,config()))
        self.assertIsNone(stock_features(price,[],NOW,config()))

    def test_one_stock_cannot_confirm_industry_and_reduced_history_reduces_confidence(self):
        full=bars();benchmark=bars('^JKSE');cfg=config()
        one=industry_features(full,['A'],benchmark,NOW,cfg)
        two=industry_features(full+bars('B'),['A','B'],benchmark,NOW,cfg)
        self.assertLess(one['coverage_confidence']['confidence'],two['coverage_confidence']['confidence'])
        result=score_industry(GRAPH[0]['winners'][0],{'A':{'industry':'Oil & Gas'}},{},full,[],GRAPH[0],[],NOW,cfg,benchmark)
        self.assertFalse(result['eligible']);self.assertTrue(any('two independent' in b for b in result['blockers']))
        short=industry_features(bars(count=30)+bars('B',30),['A','B'],benchmark,NOW,cfg)
        self.assertLess(short['coverage_confidence']['confidence'],two['coverage_confidence']['confidence'])
        self.assertIsNone(short['market']['relative63']);self.assertIsNone(short['market']['relative126'])
        self.assertIsNotNone(short['market']['relative21'])

    def test_rally_extension_and_missing_endpoint_are_explicit(self):
        rows=bars();benchmark=bars('^JKSE')
        rows[-1]['close']*=2
        f=stock_features(rows,benchmark,NOW,config());self.assertTrue(f['overextended'])
        del rows[-22]
        f=stock_features(rows,benchmark,NOW,config());self.assertNotIn(21,f['relative'])

    def test_shipping_filter_maps_to_transport_sector(self):
        tags=impacts('Tarif angkut perkapalan naik akibat gangguan rute pelayaran')
        self.assertTrue(any(t['sector']=='IDXTRANS' for t in tags))

class YahooAccuracyTests(unittest.TestCase):
    def test_direct_valuation_prevents_mixed_currency_pbv(self):
        details={'profile':{'symbol':'SMDR.JK','currency':'IDR','financialCurrency':'USD'},'metrics':{'priceToBook':11117.646}}
        apply_price_book(details,pd.DataFrame({'Current':{'Price/Book':.655807}}),'2026-10-22T00:00:00Z')
        self.assertEqual(details['metrics']['priceToBook'],.655807)
        self.assertEqual(details['profile']['metricProvenance']['priceToBook']['raw_info_value'],11117.646)
        self.assertIsNone(protect_unverified_pbv({'profile':{},'metrics':{'priceToBook':11117}})['metrics']['priceToBook'])

    def test_absent_current_never_uses_previous_year_value(self):
        details={'profile':{'symbol':'A.JK'},'metrics':{'priceToBook':9}}
        with self.assertRaises(ValueError):apply_price_book(details,pd.DataFrame({'2025':{'Price/Book':.6}}),'now')
        self.assertEqual(details['metrics']['priceToBook'],9)

    def test_financials_keep_actual_periods_with_five_year_cap(self):
        frame=pd.DataFrame({pd.Timestamp('2019-12-31'):{'TotalRevenue':1},pd.Timestamp('2025-12-31'):{'TotalRevenue':2},pd.Timestamp('2027-12-31'):{'TotalRevenue':3}})
        rows=normalize_statement(frame,'income','yearly','USD',NOW)
        self.assertEqual([r['period_end'] for r in rows],['2025-12-31']);self.assertEqual(rows[0]['line_items']['TotalRevenue'],2)

if __name__=='__main__':unittest.main()
