import copy
import unittest
from unittest.mock import patch
import pandas as pd
from services.research_api.cloud import SupabaseStore,CloudUnavailable
from services.research_api.stock_enrichment import collect_research,news_rows,run_enrichment

class Ticker:
    @property
    def valuation(self):return pd.DataFrame({'Current':{'Price/Book':0.}})
    def get_info(self):return {'symbol':'AUTO.JK','longName':'Example','currency':'IDR','marketCap':100,'priceToBook':0}
    def get_major_holders(self):return pd.DataFrame({'Value':{'insidersPercentHeld':.8,'institutionsCount':12}})
    def get_institutional_holders(self):return pd.DataFrame()
    def get_mutualfund_holders(self):return pd.DataFrame({'Holder':['Example Fund'],'pctHeld':[.02],'Shares':[100]})
    def get_news(self,**kwargs):return []

class StockAdminTests(unittest.TestCase):
    def test_soft_delete_and_reactivate_use_same_ticker_and_require_readback(self):
        c=SupabaseStore({});calls=[];state={'active':True}
        def request(path,body=None):
            calls.append((path,body));state['active']=body['enabled'];return {'symbol':body['target_symbol'],'is_active':body['enabled']}
        c.request=request;c.admin_stocks=lambda:{'stocks':[{'symbol':'AUTO.JK','is_active':state['active']}]}
        self.assertTrue(c.set_stock_active(' auto ',False)['verified'])
        self.assertTrue(c.set_stock_active('AUTO.JK',True)['verified'])
        self.assertTrue(all(p=='rpc/set_stock_active' for p,b in calls))
        self.assertEqual([b['target_symbol'] for p,b in calls],['AUTO.JK','AUTO.JK'])
        c.admin_stocks=lambda:{'stocks':[]}
        with self.assertRaises(CloudUnavailable):c.set_stock_active('AUTO',True)

    def test_invalid_admin_input_does_not_write(self):
        c=SupabaseStore({});c.request=lambda *a,**k:self.fail('Invalid input reached database')
        for value in ('AAA;DROP','ABC.US',None,'A'):
            with self.assertRaises(ValueError):c.set_stock_active(value,True)
        with self.assertRaises(ValueError):c.set_stock_active('AUTO','1')

    def test_module_empty_and_failure_preserve_previous_values_and_asof(self):
        previous={'profile':{'symbol':'AUTO.JK','ownership':{'institutions':[{'Holder':'Previous'}],'institutions_as_of':'2025-01-01'},'news':[{'title':'Old'}],'news_as_of':'2025-01-01'},'metrics':{'marketCap':200}}
        original=copy.deepcopy(previous)
        t=Ticker();t.get_info=lambda:(_ for _ in ()).throw(ValueError('Invalid info'))
        value=collect_research(t,'AUTO.JK',previous,sleep=lambda _:None)
        self.assertEqual(value['metrics']['marketCap'],200)
        self.assertEqual(value['profile']['ownership']['institutions_as_of'],'2025-01-01')
        self.assertEqual(value['profile']['news_as_of'],'2025-01-01')
        self.assertEqual(value['profile']['moduleStatus']['profile']['status'],'failed')
        self.assertEqual(value['profile']['moduleStatus']['news']['status'],'empty')
        self.assertEqual(previous,original)

    def test_access_denial_stops_remaining_source_modules(self):
        class Denied(Exception):status_code=429
        t=Ticker();t.get_info=lambda:(_ for _ in ()).throw(Denied())
        t.get_major_holders=lambda:self.fail('Source requested after rate limit')
        value=collect_research(t,'AUTO.JK',{'profile':{'symbol':'AUTO.JK'},'metrics':{'marketCap':12}},sleep=lambda _:None)
        self.assertTrue(value['access_rejected'])
        self.assertEqual(value['profile']['moduleStatus']['news']['status'],'skipped')
        self.assertEqual(value['metrics']['marketCap'],12)

    def test_ownership_and_statistics_keep_raw_units_and_zero(self):
        value=collect_research(Ticker(),'AUTO.JK',sleep=lambda _:None)
        self.assertEqual(value['metrics']['priceToBook'],0)
        self.assertEqual(value['profile']['ownership']['major']['insidersPercentHeld'],.8)
        self.assertEqual(value['profile']['ownership']['funds'][0]['pctHeld'],.02)
        self.assertEqual(value['profile']['moduleStatus']['institutional_holders']['status'],'empty')

    def test_first_ticker_access_denial_stops_batch_without_existing_snapshot(self):
        class Denied(Exception):status_code=429
        class Cloud:
            owner='test'
            def tracked(self):return ['AUTO.JK','OTHER.JK']
            def detail_state(self,s):return None
            def request(self,*a,**k):return []
        calls=[]
        def factory(symbol):
            calls.append(symbol);t=Ticker();t.get_info=lambda:(_ for _ in ()).throw(Denied());return t
        value=run_enrichment(cloud=Cloud(),ticker_factory=factory,sleep=lambda _:None)
        self.assertEqual(calls,['AUTO.JK'])
        self.assertEqual([r['status'] for r in value['results']],['failed','skipped'])

    def test_news_rejects_unsafe_urls_and_deduplicates(self):
        rows=news_rows([{'content':{'title':'Valid','canonicalUrl':{'url':'https://example.com/a'},'provider':{'displayName':'Publisher'}}},
            {'content':{'title':'Duplicate','canonicalUrl':{'url':'https://example.com/a'}}},
            {'title':'Bad','link':'javascript:alert(1)'},
            {'title':'Other stock','link':'https://example.com/b','relatedTickers':['OTHER.JK']}],'AUTO.JK')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['publisher'],'Publisher')
        self.assertIsNone(rows[0]['publishedAt'])

    def test_database_readback_failure_cannot_be_reported_verified(self):
        class Cloud:
            owner='test'
            def tracked(self):return ['AUTO.JK']
            def detail_state(self,s):return None
            def save_stock_details(self,s,d):return {'profiles':{'inserted':1}}
            def request(self,path,body=None):return []
        report=run_enrichment(cloud=Cloud(),sleep=lambda _:None,ticker_factory=lambda s:Ticker())
        self.assertEqual(report['results'][0]['status'],'failed')
        self.assertNotIn('verified',report['results'][0])

if __name__=='__main__':unittest.main()
