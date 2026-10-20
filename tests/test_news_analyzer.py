import copy
import unittest
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from services.research_api.news_analyzer import build_report, classification, generate_daily_analysis, collect_inputs, analysis_snapshot
from services.research_api.cloud import CloudUnavailable

CUTOFF=datetime(2026,10,20,5,tzinfo=timezone.utc)
def article(title,identifier='one',provider='ANTARA',published='2026-10-20T03:00:00+00:00'):
    return {'id':identifier,'title':title,'provider':provider,'url':('https://www.antaranews.com/' if provider=='ANTARA' else 'https://market.bisnis.com/')+identifier,
        'published_at':published,'first_seen_at':'2026-10-20T04:00:00+00:00','topic':'Bisnis & Market','quality_flag':'rss_headline_only'}

class FakeCloud:
    owner='test-owner'
    def __init__(self):self.rows={};self.logs=[];self.discard=False;self.articles=[article('IHSG menguat')]
    def request(self,path,body=None,prefer=None):
        table=path.split('?')[0];q=parse_qs(urlparse(path).query)
        if body is not None:
            if table=='ingestion_runs':self.logs.extend(copy.deepcopy(body));return body
            if table=='daily_market_analysis':
                fresh=[r for r in body if r['report_id'] not in self.rows]
                if not self.discard:self.rows.update({r['report_id']:copy.deepcopy(r) for r in fresh})
                return fresh
            raise AssertionError(path)
        if q.get('owner_id')!=['eq.'+self.owner]:raise AssertionError('Missing owner filter')
        if table=='news_items':return copy.deepcopy(self.articles)
        if table=='ingestion_runs':return self.logs[-1:]
        if table=='daily_market_analysis':
            rows=list(self.rows.values())
            if 'report_id' in q:rows=[r for r in rows if r['report_id']==q['report_id'][0][3:]]
            if 'report_date' in q:rows=[r for r in rows if r['report_date']==q['report_date'][0][3:]]
            return copy.deepcopy(rows[:int(q.get('limit',['200'])[0])])
        raise AssertionError(path)

class NewsAnalyzerTests(unittest.TestCase):
    def test_no_news_is_insufficient_not_neutral(self):
        r=build_report([],CUTOFF);self.assertIsNone(r['score']);self.assertEqual(r['label'],'BUKTI TERBATAS');self.assertEqual(r['article_count'],0)

    def test_no_lookahead_undated_or_unapproved_sources(self):
        unknown=article('Rupiah menguat','undated',published=None)
        future=article('Rupiah melemah','future');future['first_seen_at']='2026-10-20T06:00:00+00:00'
        bad=article('IHSG anjlok','bad');bad['url']='https://foreign.example/bad'
        r=build_report([article('IHSG menguat'),unknown,future,bad,article('IHSG turun','old',published='2026-10-19T05:00:00+00:00')],CUTOFF)
        self.assertEqual(r['article_count'],1);self.assertEqual(r['excluded'],{'outside_window':2,'undated':1,'unapproved':1})

    def test_speculation_negation_conflicts_and_multi_subject_not_scored(self):
        for title in ('IHSG diprediksi naik','Rupiah belum menguat','IHSG naik atau turun?','IHSG gagal naik','IHSG naik namun melemah lagi','IHSG naik saat rupiah melemah'):
            self.assertEqual(classification(title),[],title)

    def test_commodity_impact_is_sector_specific_not_market_bullish(self):
        r=build_report([article('Harga minyak naik')],CUTOFF)
        self.assertEqual(len(r['mixed']),1);self.assertEqual(r['positive'],[]);self.assertIn('transportasi',r['mixed'][0]['impact'])

    def test_theme_cap_dedup_and_score_formula(self):
        rows=[article('IHSG menguat '+str(i),str(i)) for i in range(8)]
        rows.extend([article('Rupiah melemah','r','Bisnis.com'),article('Suku bunga naik','s'),article('IHSG menguat 0','duplicate','Bisnis.com')])
        r=build_report(rows,CUTOFF)
        self.assertEqual(len(r['positive']),1);self.assertEqual(len(r['negative']),2);self.assertEqual(r['score'],-33.3)
        self.assertEqual(r['label'],'BEARISH');self.assertEqual(r['article_count'],10)
        self.assertEqual(r['excluded']['duplicate'],1)
        self.assertEqual(r['positive'][0]['evidence_count'],8)

    def test_mixed_reports_within_theme_cannot_vote(self):
        r=build_report([article('IHSG naik'),article('IHSG turun','two')],CUTOFF)
        self.assertEqual(len(r['mixed']),1);self.assertIsNone(r['score'])

    def test_topic_digest_covers_unscored_news_without_inventing_direction(self):
        rows=[article('The Fed akan mengumumkan suku bunga','fed'),article('Rupiah menunggu keputusan BI','rp')]
        r=build_report(rows,CUTOFF)
        self.assertEqual(len(r['unclassified']),2);self.assertEqual(sum(d['article_count'] for d in r['digests']),2)
        self.assertIn('suku bunga',r['digests'][0]['summary']);self.assertEqual(len(r['digests'][0]['evidence']),2)
        self.assertIsNone(r['score'])

    def test_report_persists_and_is_verified_idempotently(self):
        c=FakeCloud();a=generate_daily_analysis(c,CUTOFF);b=generate_daily_analysis(c,CUTOFF)
        self.assertTrue(a['database_verified']);self.assertEqual(a,b);self.assertEqual(len(c.rows),1)
        snapshot=analysis_snapshot(c,'2026-10-20');self.assertEqual(snapshot['report']['article_count'],1)
        self.assertEqual(len(snapshot['history']),1)

    def test_lost_write_fails_and_retains_previous_report(self):
        c=FakeCloud();generate_daily_analysis(c,CUTOFF);old=copy.deepcopy(c.rows);c.discard=True
        c.articles.append(article('Rupiah melemah','new'))
        with self.assertRaises(CloudUnavailable):generate_daily_analysis(c,CUTOFF)
        self.assertEqual(c.rows,old);self.assertEqual(c.logs[-1]['status'],'failed')

    def test_query_is_paginated_and_bounded(self):
        c=FakeCloud();paths=[]
        def request(path):
            paths.append(path);return [article('IHSG naik')]*500
        c.request=request
        with self.assertRaises(CloudUnavailable):collect_inputs(c,CUTOFF)
        self.assertEqual(len(paths),10);self.assertIn('first_seen_at.lte.',paths[0]);self.assertIn('offset=4500',paths[-1])

if __name__=='__main__':unittest.main()
