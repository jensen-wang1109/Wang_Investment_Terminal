"""Isolated synthetic scenarios only; never inserted into the live database."""
import copy
import unittest
from datetime import datetime,timedelta,timezone
from io import BytesIO
from services.research_api.sector_intelligence import (evaluate,macro_analytics,publication_decision,
    verified_assertion,config,GRAPH,score_industry,DEFAULTS)

NOW=datetime(2026,10,21,12,tzinfo=timezone.utc)
MAPPING={'MEDC.JK':{'sector':'IDXENERGY','industry':'Oil & Gas'},
 'ITMG.JK':{'sector':'IDXENERGY','industry':'Coal'},
 'SIMP.JK':{'sector':'IDXNONCYC','industry':'Palm Oil'},
 'ARCI.JK':{'sector':'IDXBASIC','industry':'Gold'},
 'TINS.JK':{'sector':'IDXBASIC','industry':'Tin'}}

def dataset(keys=('brent','gold','cpo')):
    return {'series':[{'id':k,'label':k,'unit':'USD / unit','frequency':'daily','source':'Official test fixture','sourceUrl':'https://www.worldbank.org/'} for k in keys],
        'observations':[{'seriesId':k,'date':(NOW-timedelta(days=70-i)).date().isoformat(),'value':100+i,
            'retrievedAt':NOW.isoformat(),'publishedAt':None} for k in keys for i in range(71)]}

def prices():
    return [{'ticker':ticker,'trade_date':(NOW-timedelta(days=90-i)).date().isoformat(),
        'close':1000+i*10,'adjusted_close':1000+i*10,'volume':10_000_000} for ticker in MAPPING for i in range(91)]

def profiles():
    return {ticker:{'retrieved_at':NOW.isoformat(),'profile':{'longBusinessSummary':'oil gas coal mining gold plantation palm'},'metrics':{'trailingPE':10}} for ticker in MAPPING}

def assertion(event,industry,factor='earnings',ticker='MEDC.JK',score=95,**kw):
    return {'id':event+industry+factor,'event_id':event,'industry':industry,'factor':factor,'ticker':ticker,
        'score':score,'material_exposure':True,'verification':'reviewed','credibility':'issuer_filing',
        'source_url':'https://www.idx.co.id/test-fixture','published_at':(NOW-timedelta(days=1)).isoformat(),
        'collected_at':NOW.isoformat(),'expires_at':(NOW+timedelta(days=30)).isoformat(),'observation_date':'2026-09-30',
        'reason':'Synthetic test evidence, not live issuer data','reviewed_by':'Unit test fixture',
        'source_excerpt':'Synthetic scenario only','measurement_basis':'Synthetic factor score for isolated acceptance test',**kw}

def assertions():
    out=[]
    for theme in GRAPH:
        for link in theme['winners']:
            ticker='SIMP.JK' if theme['id']=='v2_food' else 'ARCI.JK' if theme['id']=='v2_gold' else 'ITMG.JK' if link['industry']=='Thermal coal' else 'MEDC.JK'
            out.extend(assertion(theme['id'],link['industry'],factor,ticker) for factor in DEFAULTS['weights'])
    return out

def news(title,identifier='n'):
    return {'id':identifier,'title':title,'url':'https://www.antaranews.com/'+identifier,'provider':'ANTARA',
        'published_at':NOW.isoformat(),'first_seen_at':NOW.isoformat(),'quality_flag':'rss_headline_only'}

class IntelligenceTests(unittest.TestCase):
    def evaluate(self,**kw):
        args=dict(dataset=dataset(),news=[],mapping=MAPPING,profiles=profiles(),prices=prices(),assertions=[],previous={},now=NOW)
        args.update(kw);return evaluate(**args)

    def test_missing_earnings_valuation_exposure_never_populates_shortlist(self):
        r=self.evaluate(news=[news('Harga minyak naik')]);self.assertEqual(r['top_industries'],[])
        self.assertEqual(r['empty_message'],'No New High-Conviction Sectoral Opportunity.')
        energy=next(s for s in r['sessions'] if s['id']=='v2_energy')
        for i in energy['industries']:
            self.assertIsNone(i['factors']['earnings']['value']);self.assertIsNone(i['factors']['valuation']['value'])
            self.assertLessEqual(i['score'],30);self.assertFalse(i['eligible'])
        self.assertIsNone(publication_decision(energy,None,NOW,config()))

    def test_credible_energy_shock_evaluates_both_sides_and_gates_publication(self):
        r=self.evaluate(assertions=assertions());s=next(s for s in r['sessions'] if s['id']=='v2_energy')
        self.assertEqual(s['status'],'High Conviction');self.assertEqual(len(s['chain']),5)
        self.assertTrue(any('Air' in x['industry'] for x in s['losers']))
        self.assertEqual(publication_decision(s,None,NOW,config()),'new_high_conviction')

    def test_simultaneous_events_maximum_three_globally(self):
        r=self.evaluate(assertions=assertions())
        self.assertGreaterEqual(len(r['sessions']),3);self.assertEqual(len(r['top_industries']),3)
        self.assertEqual(len({i['industry'] for i in r['top_industries']}),3)

    def test_small_refresh_and_more_headlines_do_not_publish(self):
        r=self.evaluate(assertions=assertions());s=next(s for s in r['sessions'] if s['id']=='v2_energy')
        changed=self.evaluate(assertions=assertions(),news=[news('Harga minyak bertambah')]);new=next(x for x in changed['sessions'] if x['id']==s['id'])
        self.assertEqual(s['content_key'],new['content_key'])
        self.assertIsNone(publication_decision(new,{'payload':s,'published_at':NOW.isoformat()},NOW+timedelta(days=5),config()))

    def test_contrary_verified_evidence_invalidates_and_bypasses_cooldown(self):
        s=next(s for s in self.evaluate(assertions=assertions())['sessions'] if s['id']=='v2_energy')
        a=assertions()+[assertion('v2_energy','Upstream oil & gas',score=0,invalidates=True,id='contrary')]
        new=next(s for s in self.evaluate(assertions=a)['sessions'] if s['id']=='v2_energy')
        self.assertEqual(new['status'],'Invalidated');self.assertLess(new['score'],s['score']+1)
        self.assertFalse(any(i['industry']=='Upstream oil & gas' for i in self.evaluate(assertions=a)['top_industries']))
        self.assertEqual(publication_decision(new,{'payload':s,'published_at':NOW.isoformat()},NOW+timedelta(hours=1),config()),'verified_invalidation')

    def test_keyword_only_tin_ai_relation_rejected(self):
        r=self.evaluate(news=[news('Pusat data AI membutuhkan timah')],assertions=assertions())
        s=next(s for s in r['sessions'] if s['id']=='v2_ai')
        self.assertEqual(s['industries'],[]);self.assertNotEqual(s['status'],'High Conviction')
        self.assertFalse(any(e['ticker']=='TINS.JK' for s in r['sessions'] for i in s['industries'] for e in i['exposures']))

    def test_no_macro_and_future_or_stale_evidence_never_fills_gaps(self):
        a=assertion('v2_energy','Upstream oil & gas');a['published_at']=(NOW+timedelta(days=1)).isoformat()
        self.assertFalse(verified_assertion(a,NOW));a['published_at']=NOW.isoformat();a['expires_at']=NOW.isoformat()
        self.assertFalse(verified_assertion(a,NOW))
        self.assertEqual(self.evaluate(dataset={},assertions=[a])['top_industries'],[])

    def test_unknown_release_and_revision_preserved_future_collection_excluded(self):
        d=dataset();r=macro_analytics(d,NOW);self.assertFalse(r[0]['release_time_known']);self.assertEqual(r[0]['revision_status'],'unknown')
        d['observations'][-1]['retrievedAt']=(NOW+timedelta(days=1)).isoformat()
        r=macro_analytics(d,NOW);cpo=next(s for s in r if s['id']=='cpo');self.assertNotEqual(cpo['observation_date'],NOW.date().isoformat())

    def test_same_headline_is_not_shared_by_sessions(self):
        r=self.evaluate(news=[news('Harga minyak dan harga CPO naik')])
        self.assertEqual(sum(len(s['evidence']) for s in r['sessions']),1)

    def test_no_forced_three_and_no_claimed_macro_backtest(self):
        r=self.evaluate(dataset={});self.assertEqual(r['sessions'],[]);self.assertEqual(r['top_industries'],[])
        self.assertIn('not_validated',r['layer_status']['historical_macro_model'])
        self.assertIn('not_configured',r['layer_status']['llm'])

    def test_business_summary_required_even_with_high_scores(self):
        r=self.evaluate(assertions=assertions(),profiles={})
        self.assertEqual(r['top_industries'],[])

    def test_ordinary_upgrades_obey_cooldown(self):
        s=next(s for s in self.evaluate(assertions=assertions())['sessions'] if s['id']=='v2_energy')
        old=copy.deepcopy(s);old['status']='Monitoring';old['score']=65;old['content_key']='old'
        for i in old['industries']:i['eligible']=False
        previous={'payload':old,'published_at':NOW.isoformat()}
        self.assertIsNone(publication_decision(s,previous,NOW+timedelta(hours=1),config()))
        self.assertEqual(publication_decision(s,previous,NOW+timedelta(days=4),config()),'material_conviction_change')

    def test_easing_with_currency_pressure_is_not_unqualified_support(self):
        from services.research_api.sector_intelligence import joint_regimes
        regimes=joint_regimes([{'id':'bi','regime':'falling','stale':False},{'id':'usdidr','regime':'rising','stale':False}])
        domestic=next(r for r in regimes if r['id']=='domestic_financing')
        self.assertEqual(domestic['state'],'easing_constrained_by_fx');self.assertIn('inflation',domestic['missing_inputs'])

    def test_ephemeral_cloud_runner_preserves_failed_provider_history(self):
        from services.research_api.sector_intelligence import merge_macro_dataset
        prior=dataset(('brent','gold'));current=dataset(('gold',));current['failures']=[{'provider':'FRED','seriesId':'brent'}]
        merged=merge_macro_dataset(current,prior)
        self.assertEqual({s['id'] for s in merged['series']},{'gold','brent'})
        self.assertEqual(len(merged['observations']),len(prior['observations']))
        self.assertIsNone(next(p for p in merged['observations'] if p['seriesId']=='brent')['publishedAt'])
        self.assertEqual(merged['failures'],current['failures'])

    def test_two_page_pdf_is_revision_exact_with_real_links_no_raster_assets(self):
        from services.research_api.sector_thesis_pdf import render_sector_thesis
        from pypdf import PdfReader
        s=next(s for s in self.evaluate(assertions=assertions())['sessions'] if s['id']=='v2_energy')
        record={'payload':s,'revision':7,'published_at':NOW.isoformat()}
        reader=PdfReader(BytesIO(render_sector_thesis(record)))
        self.assertEqual(len(reader.pages),2)
        text=' '.join(p.extract_text() for p in reader.pages)
        self.assertIn('REVISION 7',text);self.assertIn('Energy supply shock',text)
        self.assertIn('not success probabilities',text)
        self.assertTrue(any(p.get('/Annots') for p in reader.pages))
        self.assertFalse(any(list(p.images) for p in reader.pages))

class MacroTransportTests(unittest.TestCase):
    def setUp(self):
        import importlib.util,tempfile
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('macro_collector_test',Path(__file__).resolve().parents[1]/'scripts/fetch-macro.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.module.RAW=Path(self.temp.name)

    def test_cached_response_preserves_real_collection_clock(self):
        from unittest.mock import patch,MagicMock
        response=MagicMock();response.__enter__.return_value=response;response.read.return_value=b'observation_date,DFEDTARU\n2026-10-20,4.0\n';response.headers={}
        with patch.object(self.module,'urlopen',return_value=response) as download:
            first=self.module.fetch('https://fred.stlouisfed.org/test','.csv')
            second=self.module.fetch('https://fred.stlouisfed.org/test','.csv')
        self.assertEqual(download.call_count,1);self.assertEqual(first,second)

    def test_access_denial_is_not_retried(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        with patch.object(self.module,'urlopen',side_effect=HTTPError('https://fred.stlouisfed.org/test',403,'denied',{},None)) as download,patch.object(self.module.time,'sleep') as sleep:
            with self.assertRaises(HTTPError):self.module.fetch('https://fred.stlouisfed.org/test','.csv')
        self.assertEqual(download.call_count,1);sleep.assert_not_called()

    def test_html_is_not_cached_as_a_successful_data_response(self):
        from unittest.mock import patch,MagicMock
        response=MagicMock();response.__enter__.return_value=response;response.read.return_value=b'<!doctype html><html>Unavailable</html>';response.headers={}
        with patch.object(self.module,'urlopen',return_value=response):
            with self.assertRaisesRegex(ValueError,'HTML response'):self.module.fetch('https://fred.stlouisfed.org/test','.csv')
        self.assertEqual(list(self.module.RAW.glob('response-*.json')),[])

if __name__=='__main__':unittest.main()
