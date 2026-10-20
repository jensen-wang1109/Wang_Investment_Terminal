"""Server-side, text-first investment brief. No remote assets or article scraping."""
from io import BytesIO
from pathlib import Path
from html import escape
from datetime import datetime, timedelta, timezone

def render_brief(report):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.pagesizes import A4
    from .feeds import approved_article
    normal,bold='Helvetica','Helvetica-Bold'
    if Path('C:/Windows/Fonts/arial.ttf').exists():
        if 'WangSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('WangSans','C:/Windows/Fonts/arial.ttf'))
            pdfmetrics.registerFont(TTFont('WangSansBold','C:/Windows/Fonts/arialbd.ttf'))
            pdfmetrics.registerFontFamily('WangSans',normal='WangSans',bold='WangSansBold',italic='WangSans',boldItalic='WangSansBold')
        normal,bold='WangSans','WangSansBold'
    ink=HexColor('#183344');muted=HexColor('#587181');teal=HexColor('#0b7770');line=HexColor('#dce5e9')
    def style(name,size=10,leading=15,**kw):return ParagraphStyle(name,fontName=normal,fontSize=size,leading=leading,textColor=ink,spaceAfter=8,**kw)
    body=style('Body');small=style('Small',8,12)
    small.textColor=muted
    heading=ParagraphStyle('Section',fontName=bold,fontSize=13,leading=18,textColor=ink,spaceBefore=15,spaceAfter=9,keepWithNext=True)
    title=ParagraphStyle('Title',fontName=bold,fontSize=29,leading=35,textColor=ink,spaceAfter=12)
    label=ParagraphStyle('Label',fontName=bold,fontSize=9,leading=13,textColor=teal,spaceAfter=8,keepWithNext=True)
    # Standard PDF fonts cannot render arbitrary punctuation reliably on Linux.
    def text(v):return escape(str(v or '').replace('−','-').replace('–','-').replace('—','-').replace('→',' / ').replace('↗','').replace('×',' x '))
    def p(v,s=body):return Paragraph(text(v),s)
    def when(v):return datetime.fromisoformat(v.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=7))).strftime('%d %b %Y, %H:%M WIB')
    sources={}
    def refs(rows):
        ids=[]
        for row in rows:
            if not approved_article(row):continue
            if row['id'] not in sources:sources[row['id']]=(len(sources)+1,row)
            ids.append(str(sources[row['id']][0]))
        return '['+', '.join(ids)+']' if ids else ''
    out=BytesIO();width,height=A4;usable=width-96
    doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=48,leftMargin=48,topMargin=66,bottomMargin=55,
        title='Wang Investment Terminal - Daily Market Thesis',author='Wang Investment Terminal')
    def footer(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(line);canvas.line(48,height-39,width-48,height-39)
        canvas.setFont(bold,8);canvas.setFillColor(teal);canvas.drawString(48,height-28,'WANG  /  INVESTMENT INTELLIGENCE')
        canvas.setFont(normal,8);canvas.setFillColor(muted);canvas.drawRightString(width-48,height-28,'DAILY MARKET THESIS')
        canvas.line(48,39,width-48,39);canvas.setFont(normal,7)
        canvas.drawString(48,26,'Riset pribadi | Ringkasan judul berita | Bukan instruksi transaksi')
        canvas.drawRightString(width-48,26,f'{report["report_date"]}  /  {doc.page}')
        canvas.restoreState()
    story=[p('DAILY BRIEF  /  '+report['report_date'],label),p('Market Thesis',title),
        p('Konteks pasar, katalis dan risiko dalam satu ringkasan.',body),
        p('Jenis laporan: '+{'morning':'Pagi','close':'Setelah penutupan IDX','manual':'Pembaruan manual'}.get(report.get('session'),'Arsip laporan'),small),
        p('Jendela berita: '+when(report['window_start'])+' - '+when(report['window_end']),small)]
    score='Belum cukup bukti' if report['score'] is None else f'{report["score"]:+.1f} / 100'
    stats=Table([[p('SENTIMEN BERITA',label),p('COMPOSITE SCORE',label),p('CAKUPAN',label)],
        [p(report['label']),p(score),p(str(report['article_count'])+' judul / '+str(len(report['providers']))+' penerbit')]],colWidths=[usable*.35,usable*.30,usable*.35])
    stats.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),HexColor('#eff6f5')),('BOX',(0,0),(-1,-1),.5,line),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,0),12),('BOTTOMPADDING',(0,-1),(-1,-1),10)]))
    story.extend([Spacer(1,12),stats,p('01  /  Executive view',heading),p(report['conclusion']),
        p('Cakupan analisis: '+report['scope_note'],small)])
    for section,items in [('02  /  Faktor pendukung',report['positive']),('03  /  Faktor penekan',report['negative']),('04  /  Dampak sektoral dan sinyal campuran',report['mixed'])]:
        story.append(p(section,heading))
        if not items:story.append(p('Belum ada tema yang memenuhi aturan pada bagian ini.',small))
        for item in items:
            source_ref=refs(item['evidence'])
            story.extend([p(item['theme']+' '+source_ref,label),p(item['summary']),p('Mekanisme / hipotesis: '+item['impact'],small)])
    story.append(p('05  /  Agenda pemantauan',heading))
    story.append(p('Konfirmasi narasi berita dengan perubahan harga, volume, rilis makro resmi dan perkembangan kebijakan. Tesis perlu ditinjau ulang jika katalis ditunda, dampak biaya berbalik, atau pergerakan harga tidak mendukung narasi. Horizon dan probabilitas transaksi tidak diturunkan dari skor berita ini.'))
    story.append(p('06  /  Sorotan per topik',heading))
    for digest in report.get('digests',[]):
        story.extend([p(digest['topic']+' '+refs(digest['evidence'][:2]),label),p(digest['summary'])])
    story.extend([p('07  /  Metode dan keterbatasan',heading),p(report['method_note'],small),
        p('Tanggal laporan menggunakan Asia/Jakarta. Judul yang ambigu tidak diberi skor. Berita yang tersedia sesudah waktu analisis tidak dimasukkan. Ini ringkasan otomatis berbasis aturan; isi lengkap artikel belum dianalisis.',small),
        p('Report ID: '+report['report_id'],small),p('08  /  Referensi berita',heading)])
    for number,row in sources.values():
        metadata=f'{row["provider"]} | {when(row["published_at"])} | '
        story.append(KeepTogether([p(f'{number}. {row["title"]}',small),Paragraph(text(metadata)+'<link href="'+escape(row['url'],quote=True)+'" color="#0b7770">Buka sumber</link>',small)]))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
