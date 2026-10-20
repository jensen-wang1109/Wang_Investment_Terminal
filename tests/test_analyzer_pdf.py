import unittest
from io import BytesIO
from datetime import datetime,timezone
from services.research_api.news_analyzer import build_report
from services.research_api.analyzer_pdf import render_brief

class AnalyzerPdfTests(unittest.TestCase):
    def test_empty_evidence_report_remains_downloadable_without_invented_sources(self):
        from pypdf import PdfReader
        report=build_report([],datetime(2026,10,20,5,tzinfo=timezone.utc))
        pdf=PdfReader(BytesIO(render_brief(report)));text='\n'.join(p.extract_text() for p in pdf.pages)
        self.assertIn('Belum ada sumber berita',text);self.assertIn('0 judul',text)

    def test_pdf_contains_real_report_identity_and_clickable_source_without_remote_assets(self):
        from pypdf import PdfReader
        row={'id':'one','title':'IHSG menguat & investor menunggu <konfirmasi>','provider':'ANTARA','url':'https://www.antaranews.com/test',
             'topic':'Bisnis & Market','published_at':'2026-10-20T03:00:00+00:00','first_seen_at':'2026-10-20T04:00:00+00:00','quality_flag':'rss_headline_only'}
        report=build_report([row],datetime(2026,10,20,5,tzinfo=timezone.utc));report['session']='close'
        data=render_brief(report);self.assertTrue(data.startswith(b'%PDF-'))
        pdf=PdfReader(BytesIO(data));text='\n'.join(p.extract_text() for p in pdf.pages)
        for expected in ('Market Thesis','2026-10-20','BUKTI TERBATAS','Setelah penutupan IDX',report['report_id']):self.assertIn(expected,text)
        links=[a.get_object().get('/A',{}).get('/URI') for p in pdf.pages for a in p.get('/Annots',[])]
        self.assertIn(row['url'],links)
        for page in pdf.pages:self.assertNotIn('/XObject',page.get('/Resources',{}))

if __name__=='__main__':unittest.main()
