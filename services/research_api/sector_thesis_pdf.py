"""Two-page, revision-exact research note. No network or invented chart data."""
from io import BytesIO
from html import escape
from pathlib import Path

def render_sector_thesis(record):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    thesis=record['payload'];out=BytesIO();w,h=A4
    c=Canvas(out,pagesize=A4);c.setTitle(f"Wang Investment Thesis - {thesis['title']} - r{record['revision']}")
    c.setAuthor('Wang Investment Research')
    normal,bold='Helvetica','Helvetica-Bold'
    if Path('C:/Windows/Fonts/arial.ttf').exists():
        if 'WangSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('WangSans','C:/Windows/Fonts/arial.ttf'))
            pdfmetrics.registerFont(TTFont('WangSansBold','C:/Windows/Fonts/arialbd.ttf'))
        normal,bold='WangSans','WangSansBold'
    ink='#173247';teal='#07877e';muted='#5c7080';left=44;usable=w-88
    def clean(x):return str(x or '').replace('→',' > ').replace('–','-').replace('—','-').replace('−','-').replace('•',' / ')
    def paragraph(text,x,y,width=usable,size=9,color=ink,max_height=60,strong=False):
        # Fixed editorial blocks are bounded. Full evidence remains in immutable JSON.
        value=clean(text);style=ParagraphStyle('p',fontName=bold if strong else normal,fontSize=size,leading=size*1.4,textColor=HexColor(color))
        while True:
            p=Paragraph(escape(value),style);_,height=p.wrap(width,max_height)
            if height<=max_height or len(value)<20:break
            value=value[:max(15,len(value)-35)].rstrip()+' ...'
        p.drawOn(c,x,y-height);return y-height
    def label(text,y):paragraph(text.upper(),left,y,size=8,color=teal,max_height=14,strong=True);return y-20
    def frame(page):
        c.setFillColor(HexColor(ink));c.rect(0,h-12,w,12,fill=1,stroke=0)
        paragraph('WANG INVESTMENT RESEARCH',left,h-32,size=8,color=teal,strong=True,max_height=15)
        paragraph(f"{record.get('published_at',thesis['updated_at'])[:10]}  /  REVISION {record['revision']}",w-238,h-32,width=195,size=8,color=muted,max_height=15)
        c.setStrokeColor(HexColor('#dbe5e9'));c.line(left,42,w-left,42)
        paragraph('SECTORAL INTELLIGENCE  /  PERSONAL RESEARCH  /  NOT A TRADE SIGNAL',left,32,size=6.6,color=muted,max_height=12)
        c.setFont(normal,8);c.drawRightString(w-left,23,str(page))
    frame(1);y=h-71
    y=paragraph(thesis['title'],left,y,size=23,max_height=70,strong=True)-10
    y=paragraph(f"{thesis['status']}  |  1-6 MONTH OUTLOOK  |  THESIS SCORE {thesis['score']:g}/100",left,y,size=9,color=teal,strong=True,max_height=18)-18
    y=label('01 / Investment view',y)
    y=paragraph(thesis['forecast']+' '+thesis['pricing'],left,y,max_height=66)-15
    y=label('02 / Economic transmission',y)
    for step in thesis['chain']:
        c.setFillColor(HexColor('#eff7f6'));c.roundRect(left,y-26,usable,25,4,fill=1,stroke=0)
        paragraph(step,left+10,y-5,width=usable-20,size=8.4,max_height=22);y-=30
    y-=10;y=label('03 / Observed macro evidence',y)
    indicators=thesis.get('indicators',[])[:4]
    for item in indicators:
        y=paragraph(f"{item['name']}: {item['value']:g} {item['unit']} | period {item['observation_date']} | {item['frequency']}"+(' | STALE' if item['stale'] else '')+(' | retained after source failure' if item.get('retrieval_status')=='failed_retained' else ''),left,y,size=8,max_height=25)-3
    if not indicators:y=paragraph('No sufficient current quantitative series for this event. Headline evidence is not numerical confirmation.',left,y,size=8,color=muted,max_height=30)-5
    charts=[x for x in thesis.get('quantitative_charts',[]) if len(x['points'])>=2]
    if charts and y>235:
        chart=charts[0];points=chart['points'];values=[p['value'] for p in points];low=min(values);high=max(values);span=high-low or max(abs(high)*.01,1)
        chart_y=y-100;plotw=usable-62;ploth=65
        paragraph(chart['name']+' / '+chart['unit']+' / '+chart['frequency'],left,y,size=8,color=muted,max_height=16)
        c.setStrokeColor(HexColor('#dbe5e9'));c.line(left+38,chart_y,left+38+plotw,chart_y)
        c.setStrokeColor(HexColor(teal));c.setLineWidth(1.4)
        # Actual observation dates are proportional, not invented evenly spaced release dates.
        from datetime import date
        dates=[date.fromisoformat(p['date']).toordinal() for p in points];duration=dates[-1]-dates[0] or 1
        path=c.beginPath()
        for i,(dt,value) in enumerate(zip(dates,values)):
            x=left+38+(dt-dates[0])/duration*plotw;cy=chart_y+(value-low)/span*ploth
            if i:path.lineTo(x,cy)
            else:path.moveTo(x,cy)
        c.drawPath(path)
        paragraph(f'{high:,.2f}',left,chart_y+ploth+6,width=36,size=7,max_height=15)
        paragraph(f'{low:,.2f}',left,chart_y+8,width=36,size=7,max_height=15)
        paragraph(points[0]['date']+' to '+points[-1]['date'],left+38,chart_y-5,width=plotw,size=7,color=muted,max_height=14)
        y=chart_y-28
    else:y=paragraph('Chart omitted: sufficient quantitative observations / page space unavailable. No simulated series used.',left,y,size=7.5,color=muted,max_height=24)-12
    y=label('04 / Industry shortlist & execution gates',y)
    for i in sorted(thesis['industries'],key=lambda x:-x['score'])[:3]:
        y=paragraph(f"{i['industry']} | {i['score']:g}/100 | coverage confidence {i['data_quality']:g}/100 | {'eligible' if i['eligible'] else 'research hypothesis'}",left,y,size=8.3,strong=True,max_height=27)-3
        y=paragraph(i['earnings_effect'],left,y,size=8,max_height=27)-8
    if not thesis['industries']:paragraph('No verified beneficiary industry is shortlisted.',left,y,size=8,max_height=25)
    c.showPage();frame(2);y=h-72
    y=label('05 / Adversely affected industries',y)
    for i in thesis['losers'][:2]:y=paragraph(i['industry']+': '+i['mechanism'],left,y,size=8.5,max_height=40)-7
    y-=6;y=label('06 / Scenarios (conditional, not probabilities)',y)
    for name,text in thesis['scenarios'].items():y=paragraph(name.upper()+': '+text,left,y,size=8.5,max_height=35)-7
    y-=6;y=label('07 / Invalidation & monitoring',y)
    for text in (thesis['invalidate']+thesis['checks'])[:5]:y=paragraph('- '+text,left,y,size=8.3,max_height=32)-5
    y-=7;y=label('08 / Evidence and sources',y)
    sources=[]
    for i in thesis.get('indicators',[]):sources.append((i['name']+' / '+i['observation_date'],i['source_url']))
    for a in thesis.get('assertions',[]):sources.append((a['factor']+' / '+a['reason'],a['source_url']))
    for a in thesis.get('evidence',[])[:3]:sources.append((a['provider']+' / '+a['title'],a['url']))
    sources.append(('Mechanism reference (not current confirmation)',thesis['reference']))
    from .sector_intelligence import valid_url
    unique=[];seen=set()
    for title,url in sources:
        if valid_url(url) and url not in seen:unique.append((title,url));seen.add(url)
    for number,(title,url) in enumerate(unique[:7],1):
        before=y;y=paragraph(f'[{number}] '+title,left,y,width=usable-35,size=7.5,color=muted,max_height=24)-5
        c.linkURL(url,(left,before-24,w-left,before),relative=0,thickness=0)
        paragraph('LINK',w-left-29,before,width=29,size=7,color=teal,max_height=12)
    y-=10;y=label('09 / Method and limits',y)
    methodology=thesis.get('methodology')
    if methodology:
        weights=', '.join(f'{k} {v:g}%' for k,v in methodology['weights'].items())
        method='Macro-driven research weights: '+weights+'. Missing metrics excluded; available weights normalized. Data Coverage Confidence is separate (count/history/diversification); one stock cannot confirm an industry. Benchmark: actual IHSG. Extended rallies excluded from shortlist. Company fundamentals are not scoring inputs. Scores are research strength, not success probabilities. Combined macro model has not passed point-in-time validation. Selected revision and full evidence remain in the application.'
    else:
        method='Archived methodology: macro 20%, supply/demand 20%, earnings 25%, catalyst 10%, valuation 15%, market 10%. Missing factors were not reweighted. Scores are thesis strength, not success probabilities. Full source metadata and selected revision are retained in the application.'
    paragraph(method,left,y,size=7.7,color=muted,max_height=83)
    c.save();return out.getvalue()
