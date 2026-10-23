"""Synthetic fixtures never enter the application's live database."""
import copy,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from services.research_api.indonesia_intelligence import build_indonesia,market_features,stable_regime,event_metadata,VERSION
from services.research_api.intelligence_memory import realized_outcomes
NOW=datetime(2026,10,23,12,tzinfo=timezone.utc)

def market(symbol='^JKSE',trend=1.001):
    rows=[{'date':(NOW-timedelta(days=80-i)).date().isoformat(),'value':100*trend**i,'volume':1000,'retrieved_at':NOW.isoformat()} for i in range(81)]
    return {'symbol':symbol,'name':symbol,'value':rows[-1]['value'],'observation_date':rows[-1]['date'],'source_url':'https://example.org','features':market_features(rows,NOW)}

def context():return {'prices':[market(),market('IDR=X',.999)],'signals':[]}

class IndonesiaTests(unittest.TestCase):
    def test_ihsg_and_currency_present_with_missing_macro_no_fabricated_economic_cycle(self):
        result=build_indonesia(context(),[],{},NOW)
        self.assertEqual(result['economic_regime']['current'],'Uncertain / Mixed')
        self.assertEqual(result['equity_regime']['current'],'Bullish')
        self.assertEqual(result['rupiah']['outlook'],'Rupiah strengthening bias')
        self.assertEqual(result['ihsg']['macro_supported_outlook'],'Insufficient Evidence')
        self.assertEqual(result['changes'],[]);self.assertEqual(result['change_message'],'No Material Macro Change.')
        self.assertGreaterEqual(len(result['executive_summary'].split()),100);self.assertLessEqual(len(result['executive_summary'].split()),150)

    def test_missing_or_stale_market_cannot_give_directional_outlook(self):
        r=build_indonesia({'prices':[],'signals':[]},[],{},NOW)
        self.assertEqual(r['ihsg']['outlook'],'Insufficient Evidence');self.assertEqual(r['rupiah']['outlook'],'Insufficient Evidence')
        rows=[{'date':'2026-10-01','value':100}];f=market_features(rows,NOW)
        self.assertEqual(f['status'],'stale');self.assertEqual(f['last_date'],'2026-10-01')

    def test_one_day_regime_flip_is_held_but_missing_data_is_not_masked(self):
        old=stable_regime('Bullish',None,NOW,[],[],'moderate')
        first=stable_regime('Bearish',old,NOW+timedelta(days=1),[],[],'moderate')
        same_day=stable_regime('Bearish',first,NOW+timedelta(days=1,hours=1),[],[],'moderate')
        self.assertEqual(first['current'],'Bullish');self.assertEqual(same_day['persistence'],1)
        second=stable_regime('Bearish',same_day,NOW+timedelta(days=2),[],[],'moderate')
        self.assertEqual(second['current'],'Bearish');self.assertTrue(second['materially_changed'])
        self.assertEqual(stable_regime('Insufficient Evidence',second,NOW,[],[],'low')['current'],'Insufficient Evidence')

    def test_duplicate_news_is_not_independent_confirmation_and_global_low_impact_excluded(self):
        a={'title':'Harga minyak naik','url':'https://a.example/news','published_at':NOW.isoformat()}
        s={'id':'energy','title':'energy','macro':'conditional Indonesia transmission','confirm':[],'evidence':[a,{**a,'url':'https://b.example/news'}]}
        events=event_metadata({'signals':[s]},None,NOW)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['independent_confirmations'],0);self.assertEqual(events[0]['materiality'],'MODERATE')
        s['id']='global_equities';self.assertEqual(event_metadata({'signals':[s]},None,NOW)[0]['materiality'],'LOW')

    def test_price_future_duplicate_and_missing_data_not_imputed(self):
        rows=[{'date':'2026-10-21','value':100},{'date':'2026-10-21','value':110},{'date':'2026-10-22','value':101},{'date':'2026-10-25','value':999}]
        r=market_features(rows,NOW);self.assertEqual(r['observations'],1);self.assertEqual(r['value'],101)

    def test_changes_compare_previous_day_not_repeated_headlines(self):
        old=build_indonesia(context(),[],{},NOW)
        c=context();c['prices'][0].update(value=c['prices'][0]['value']*1.02,observation_date='2026-10-24')
        r=build_indonesia(c,[],old,NOW+timedelta(days=1));self.assertEqual(len(r['changes']),1);self.assertEqual(r['changes'][0]['title'],'^JKSE')

    def test_outcome_uses_next_session_and_frozen_members_not_survivors(self):
        benchmark=[{'trade_date':(NOW+timedelta(days=i)).date().isoformat(),'close':100+i} for i in range(140)]
        prices=[{'ticker':ticker,**r} for ticker in ('A','B') for r in benchmark]
        thesis={'session_id':'v2_energy','revision':1,'published_at':NOW.isoformat(),'payload':{'version':VERSION,'industries':[{'eligible':True,'industry':'Oil','score':90,'exposures':[{'ticker':'A','technical':{}},{'ticker':'B','technical':{}}]}]}}
        # Technical dictionaries must be present; empty dict still indicates a frozen member.
        for e in thesis['payload']['industries'][0]['exposures']:e['technical']={'date':'2026-10-23'}
        outcomes,pending=realized_outcomes([thesis],prices,benchmark,'2027-03-11')
        self.assertEqual(len(outcomes),3);self.assertEqual(outcomes[0]['entry_date'],'2026-10-24');self.assertEqual(outcomes[0]['excess_return'],0)
        no_future,pending=realized_outcomes([thesis],prices,benchmark,'2026-11-01');self.assertEqual(no_future,[]);self.assertEqual(pending,3)

    def test_daily_write_readback_failure_preserves_previous_report_and_logs_failure(self):
        from services.research_api.daily_intelligence import daily_report
        from services.research_api.cloud import CloudUnavailable
        class Cloud:
            owner='fixture'
            logs=[]
            def request(self,path,body=None,prefer=None):
                if path.startswith('ingestion_runs'):self.logs.extend(body);return body
                return [] # Deliberately drop the write.
        ctx={'analysis_id':'a'*64,'indonesia':build_indonesia(context(),[],{},NOW),'news_count':0,'model':{},'publication_cutoff':NOW.isoformat(),'knowledge_cutoff':NOW.isoformat()}
        c=Cloud()
        with patch('services.research_api.shared_intelligence.refresh_shared_context'),patch('services.research_api.shared_intelligence.shared_snapshot',return_value={'context':ctx}):
            with self.assertRaises(CloudUnavailable):daily_report(c,now=NOW,run_sector=False)
        self.assertEqual(c.logs[-1]['status'],'failed')

if __name__=='__main__':unittest.main()
