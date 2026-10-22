import unittest
from datetime import datetime,timedelta,timezone
from services.research_api.shared_intelligence import build_context,claim_state,shared_snapshot
from services.research_api.macro_classifier import classify_texts,trained_classifier
NOW=datetime(2026,10,22,8,tzinfo=timezone.utc)
class SharedIntelligenceTests(unittest.TestCase):
 def fact(self):return {'id':'msci','verification_status':'primary_source_verified','verified_at':NOW.isoformat(),'source_url':'https://www.msci.com/','event_state':'consultation_proposal'}
 def test_proposal_denial_and_final_claim_are_not_conflated(self):
  self.assertEqual(claim_state('MSCI resmi membuka konsultasi usulan reklasifikasi standalone'),'proposal_or_scenario')
  self.assertEqual(claim_state('MSCI belum memutuskan downgrade Indonesia'),'negated_or_uncertain')
  self.assertEqual(claim_state('MSCI resmi menurunkan Indonesia ke standalone'),'final_decision_claim')
  self.assertEqual(claim_state('MSCI membatalkan konsultasi standalone'),'cancellation_claim')
 def test_stale_or_future_fact_cannot_be_current_confirmed_evidence(self):
  for stamp in [NOW-timedelta(days=4),NOW+timedelta(days=1)]:
   fact={**self.fact(),'verified_at':stamp.isoformat()}
   context=build_context([], [fact],[],{}, {},[],NOW)
   self.assertFalse(context['signals'])
 def test_msci_risk_does_not_invent_beneficiaries_or_outflow_estimates(self):
  context=build_context([], [self.fact()],[],{}, {},[],NOW)
  s=context['signals'][0];self.assertEqual(s['state'],'consultation_proposal');self.assertEqual(s['beneficiaries'],[])
  self.assertIn('tidak dihitung',s['macro'])
 def test_energy_impacts_are_two_sided_and_require_tanker_confirmation(self):
  news=[{'title':'Harga minyak berisiko naik','id':'a','published_at':NOW.isoformat()}]
  context=build_context(news,[],[],{}, {},[{'topic':'energy','topic_score':.7}],NOW)
  s=context['signals'][0];self.assertTrue(s['pressured']);self.assertFalse(any(i['eligible_recommendation'] for i in s['beneficiaries']))
  tanker=next(i for i in s['beneficiaries'] if 'Tanker' in i['industry']);self.assertIn('minyak naik saja tidak cukup',tanker['condition'])
 def test_shared_snapshot_is_owner_scoped_and_cutoff_is_publication_time(self):
  class Cloud:
   owner='fixture'
   def request(self,path):
    self.path=path;return [{'payload':{'context':{'analysis_id':'same-context'}}}]
  c=Cloud();a=shared_snapshot(c,NOW.isoformat());self.assertIn('owner_id=eq.fixture',c.path);self.assertIn('publication_cutoff',c.path);self.assertEqual(a['context']['analysis_id'],'same-context')
 def test_trained_model_has_held_out_validation_and_rejects_unrelated_msci_evidence(self):
  pred,report=classify_texts(['Reli Nasdaq didorong saham SpaceX dan Super Micro di Wall Street','MSCI membuka konsultasi standalone Indonesia'])
  self.assertNotEqual(pred[0]['topic'],'market_access');self.assertEqual(pred[1]['topic'],'market_access')
  self.assertGreater(report['macro_f1'],.7);self.assertFalse(report['return_prediction_validated']);self.assertEqual(report['validation_rows'],30)
if __name__=='__main__':unittest.main()
