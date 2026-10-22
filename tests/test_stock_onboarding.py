import copy
import unittest
from unittest.mock import patch
from services.research_api.stock_onboarding import sync_one
from services.research_api.stock_classification import create_sector,create_industry,save_mapping,apply_overlay
from services.research_api.cloud import CloudUnavailable

class Cloud:
    owner='owner';env={};transport=None
    def __init__(self):self.rows=[];self.writes=0
    def tracked(self):return ['TLKM.JK']
    def request(self,path,body=None,**kwargs):
        if body:
            self.rows=copy.deepcopy(body);self.writes+=1;return body
        if path.startswith('sector_macro_context?'):return self.rows
        if path.startswith('companies?'):return [{'id':1}]
        raise AssertionError(path)
    def sector_tree(self):
        return apply_overlay(self,{'sectors':[{'id':10,'code':'IDXINFRA','name':'Infrastructures','stock_count':0,'industries':[{'id':'telecom','name':'Telecommunication','stocks':[]}]}],
            'unmapped':[{'symbol':'TLKM.JK','name':'Telkom'}],'industry_count':1})

class OnboardingTests(unittest.TestCase):
    def test_first_activation_downloads_eod_then_research_with_readback_gate(self):
        c=Cloud();calls=[]
        def eod(**kwargs):calls.append(('price',kwargs['ticker']));return {'status':'success','database_verified':True,'verified_rows':1200}
        def research(symbols,cloud):calls.append(('research',symbols[0]));return {'results':[{'verified':True,'status':'success'}]}
        result=sync_one('TLKM.JK',c,eod,research)
        self.assertEqual(calls,[('price','TLKM.JK'),('research','TLKM.JK')]);self.assertEqual(result['status'],'success')
    def test_price_failure_is_visible_and_stops_more_source_requests(self):
        def research(*a,**k):self.fail('Research called after price failure')
        r=sync_one('TLKM.JK',Cloud(),lambda **k:{'status':'failed'},research)
        self.assertEqual(r['status'],'failed');self.assertIsNone(r['prices']['database_verified'])
    def test_deactivated_queued_stock_is_not_downloaded(self):
        c=Cloud();c.tracked=lambda:[]
        r=sync_one('TLKM.JK',c,lambda **k:self.fail('Inactive source requested'))
        self.assertEqual(r['status'],'skipped')
    def test_profile_failure_does_not_discard_verified_prices(self):
        r=sync_one('TLKM.JK',Cloud(),lambda **k:{'database_verified':True},lambda *a,**k:{'results':[{'status':'failed'}]})
        self.assertEqual(r['status'],'partial');self.assertTrue(r['prices']['database_verified'])
    def test_dynamic_taxonomy_is_persisted_and_remaps_same_stock_without_duplicates(self):
        c=Cloud();s=create_sector(c,{'name':'Digital economy','code':'RESEARCH_DIGITAL'})['sector']
        i=create_industry(c,{'name':'Connectivity','sector_id':s['id']})['industry']
        self.assertEqual(create_industry(c,{'name':'connectivity','sector_id':s['id']})['industry']['id'],i['id'])
        self.assertTrue(save_mapping(c,{'symbol':'TLKM','sector_id':s['id'],'industry_id':i['id']})['verified'])
        t=c.sector_tree();matches=[x for s in t['sectors'] for i in s['industries'] for x in i['stocks']]
        self.assertEqual(len(matches),1);self.assertEqual(t['unmapped'],[])
        save_mapping(c,{'symbol':'TLKM','sector_id':10,'industry_id':'telecom'})
        t=c.sector_tree();self.assertEqual(t['sectors'][0]['industries'][0]['stocks'][0]['symbol'],'TLKM.JK')
    def test_wrong_sector_industry_pair_does_not_write(self):
        c=Cloud()
        with self.assertRaises(ValueError):save_mapping(c,{'symbol':'TLKM','sector_id':123,'industry_id':'telecom'})
        self.assertEqual(c.writes,0)
    def test_unverified_configuration_write_is_not_success(self):
        c=Cloud()
        def request(path,body=None,**kwargs):return []
        c.request=request
        with self.assertRaises(CloudUnavailable):create_sector(c,{'name':'Custom','code':'CUSTOM'})

if __name__=='__main__':unittest.main()
