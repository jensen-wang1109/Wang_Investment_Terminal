import copy,unittest,math
from datetime import datetime,timedelta,timezone
from services.research_api.sector_trends import candidates_from_news
from services.research_api.sector_model import splits,predict,feature_panel,HORIZONS

NOW=datetime(2026,10,20,12,tzinfo=timezone.utc)
MAPPING={'SIMP.JK':{'sector':'IDXNONCYC','industry':'Palm Oil'},'DCII.JK':{'sector':'IDXTECHNO','industry':'Data Center, AI & Cloud Infrastructure'}}
def news(title,id,provider='ANTARA',age=1):
    host='https://www.antaranews.com/' if provider=='ANTARA' else 'https://market.bisnis.com/'
    return {'id':id,'title':title,'url':host+id,'provider':provider,'published_at':(NOW-timedelta(hours=age)).isoformat(),'first_seen_at':(NOW-timedelta(minutes=1)).isoformat(),'topic':'Bisnis & Market','quality_flag':'rss_headline_only'}

class SectorTrendTests(unittest.TestCase):
    def test_new_evidence_same_stage_does_not_change_material_key(self):
        rows=[news('Mandatori B50 resmi diluncurkan','a'),news('Realisasi B50 meningkatkan serapan biodiesel','b','Bisnis.com')]
        first=candidates_from_news(rows,MAPPING,[],NOW)[0]
        self.assertEqual(first['status'],'supported');self.assertEqual(first['industries'][0]['tickers'],['SIMP.JK'])
        rows.insert(0,news('B50 resmi berjalan untuk energi domestik','c','Bisnis.com'))
        second=candidates_from_news(rows,MAPPING,[],NOW)[0]
        self.assertEqual(first['material_key'],second['material_key'])

    def test_contradiction_and_expiry_are_material(self):
        rows=[news('Mandatori B50 resmi diluncurkan','a'),news('Realisasi B50 meningkatkan permintaan','b','Bisnis.com')]
        first=candidates_from_news(rows,MAPPING,[],NOW)[0];previous=[{'theme_id':'biodiesel','payload':first}]
        adverse=candidates_from_news(rows+[news('B50 ditunda sementara','c','Bisnis.com')],MAPPING,previous,NOW)[0]
        self.assertEqual(adverse['status'],'contested');self.assertNotEqual(first['material_key'],adverse['material_key'])
        expired=candidates_from_news([],MAPPING,previous,NOW)[0];self.assertEqual(expired['status'],'expired')

    def test_single_publisher_future_unapproved_and_syndication_not_enough(self):
        for rows in ([news('B50 resmi berjalan','a')],[news('B50 resmi berjalan','a'),news('B50 resmi berjalan','b','Bisnis.com')]):
            self.assertEqual(candidates_from_news(rows,MAPPING,[],NOW),[])
        a=news('B50 resmi berjalan','a');b=news('Implementasi B50 meningkat','b','Bisnis.com');b['first_seen_at']=(NOW+timedelta(hours=1)).isoformat()
        self.assertEqual(candidates_from_news([a,b],MAPPING,[],NOW),[])
        b['first_seen_at']=NOW.isoformat();b['url']='https://foreign.example/';self.assertEqual(candidates_from_news([a,b],MAPPING,[],NOW),[])

    def test_rate_hikes_are_not_mislabeled_as_monetary_support(self):
        rows=[news('Suku bunga naik kembali','a'),news('BI-Rate naik pada bulan ini','b','Bisnis.com')]
        c=candidates_from_news(rows,MAPPING,[],NOW)[0]
        self.assertEqual(c['id'],'monetary');self.assertEqual(c['status'],'risk')

    def test_purged_splits_have_no_label_overlap_and_are_chronological(self):
        base=datetime(2021,1,1);rows=[]
        for i in range(200):
            day=base+timedelta(days=7*i)
            for h in HORIZONS:rows.append({'date':day.date().isoformat(),'label_end':(day+timedelta(days=math.ceil(h*7/5))).date().isoformat(),'horizon':h})
        for h in HORIZONS:
            folds=list(splits(rows,h));self.assertEqual(len(folds),3)
            for train,test in folds:self.assertLess(max(r['label_end'] for r in train),min(r['date'] for r in test))

    def test_json_parameters_predict_without_unpickling_or_unbounded_exp(self):
        report={'sector_order':['TEST'],'models':[{'horizon':21,'approx_months':1,'statistical_gate_passed':False,'parameters':{'mean':[0,0],'scale':[1,1],'class_coef':[10000,0],'class_intercept':0,'return_coef':[.1,0],'return_intercept':0}}]}
        p=predict(report,[{'sector':'TEST','date':'2026-10-20','x':[1]}])[0]
        self.assertTrue(math.isfinite(p['probability']));self.assertGreater(p['probability'],.99);self.assertEqual(p['deployment_status'],'research_only')

    def test_future_prices_cannot_change_past_features_or_mature_labels(self):
        import numpy as np
        from services.research_api.idx_calendar import session_dates
        sessions=session_dates('2021-01-01','2025-12-31');mapping={'AAA.JK':{'sector':'A'},'BBB.JK':{'sector':'B'}};rng=np.random.default_rng(42);rows=[]
        for ticker in mapping:
            price=1000.
            for day in sessions:
                price*=math.exp(float(rng.normal(0,.01)));rows.append({'ticker':ticker,'trade_date':day,'close':price,'adjusted_close':price,'volume':10000})
        original,_,_=feature_panel(rows,mapping);changed=copy.deepcopy(rows);cutoff='2024-01-01'
        for r in changed:
            if r['trade_date']>cutoff:r['adjusted_close']*=5;r['close']*=5
        modified,_,_=feature_panel(changed,mapping)
        before={(r['sector'],r['date'],r['horizon']):(r['x'],r['excess']) for r in original if r['label_end']<=cutoff}
        after={(r['sector'],r['date'],r['horizon']):(r['x'],r['excess']) for r in modified if r['label_end']<=cutoff}
        self.assertEqual(before,after)

    def test_duplicates_rejected_in_training(self):
        row={'ticker':'AAA.JK','trade_date':'2025-01-02','close':1,'adjusted_close':1,'volume':1}
        with self.assertRaisesRegex(ValueError,'Duplicate'):feature_panel([row,row],{'AAA.JK':{'sector':'A'}})

if __name__=='__main__':unittest.main()
