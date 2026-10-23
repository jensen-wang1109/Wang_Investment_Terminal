"""Two-page WANG research note from an exact stored revision or evaluation."""
from io import BytesIO
from html import escape
from pathlib import Path
import re


def render_sector_thesis(record):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from .sector_intelligence import valid_url

    thesis = record['payload']; out = BytesIO(); w, h = A4
    c = Canvas(out, pagesize=A4)
    draft = bool(record.get('draft'))
    version = 'INTERNAL EVALUATION / NOT PUBLISHED' if draft else f"REVISION {record['revision']}"
    c.setTitle(f"WANG Investment Thesis - {thesis['title']} - {version}")
    c.setAuthor('WANG Investment Research')
    normal, bold = 'Helvetica', 'Helvetica-Bold'
    if Path('C:/Windows/Fonts/arial.ttf').exists():
        if 'WangSans' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('WangSans', 'C:/Windows/Fonts/arial.ttf'))
            pdfmetrics.registerFont(TTFont('WangSansBold', 'C:/Windows/Fonts/arialbd.ttf'))
        normal, bold = 'WangSans', 'WangSansBold'
    ink, red, muted, line, soft = '#1B1B1F', '#D32938', '#68686F', '#DADADF', '#F3F3F4'
    left, usable = 42, w-84
    gap = 22; col = (usable-gap)/2; right = left+col+gap

    def clean(value):
        text = re.sub(r'\byahoo(?:[\s_]+finance)?\b', 'Market data', str(value or ''), flags=re.I)
        return text.replace('→', ' > ').replace('–', '-').replace('—', '-').replace('−', '-')

    def para(text, x, y, width=usable, size=9, color=ink, height=70, strong=False):
        text = clean(text)
        style = ParagraphStyle('wang', fontName=bold if strong else normal,
                               fontSize=size, leading=size*1.43, textColor=HexColor(color))
        value = text
        while True:
            p = Paragraph(escape(value), style); _, ph = p.wrap(width, height)
            if ph <= height or len(value) < 12: break
            value = value[:max(10, len(value)-22)].rsplit(' ', 1)[0].rstrip(' .')+' ...'
        p.drawOn(c, x, y-ph)
        return y-ph

    def section(label, x, y, width=usable):
        c.setStrokeColor(HexColor(line)); c.setLineWidth(.5); c.line(x, y+5, x+width, y+5)
        para(label.upper(), x, y-6, width=width, size=7.5, color=red, height=14, strong=True)
        return y-28

    def frame(page):
        c.setFillColor(HexColor(ink)); c.rect(0, h-6, w, 6, fill=1, stroke=0)
        # Correct geometric wang / king character: three bars and one vertical.
        c.setStrokeColor(HexColor(ink)); c.setLineWidth(1.6)
        for yy, xx, length in [(h-33,left+3,18),(h-42,left+5,14),(h-51,left+1,22)]: c.line(xx,yy,xx+length,yy)
        c.line(left+12,h-33,left+12,h-51)
        para('WANG', left+34, h-31, width=130, size=13, height=20, strong=True)
        para('INVESTMENT RESEARCH', left+34, h-48, width=170, size=6.8, color=muted, height=12)
        stamp = record.get('published_at') or record.get('generated_at') or thesis['updated_at']
        para(str(stamp)[:10], w-left-145, h-31, width=145, size=8, color=muted, height=13)
        para(version, w-left-220, h-47, width=220, size=6.8, color=red if draft else muted, height=20)
        c.setStrokeColor(HexColor(line)); c.line(left, 42, w-left, 42)
        para('PERSONAL RESEARCH / 1-6 MONTH HORIZON / NOT A TRADE INSTRUCTION', left, 32, size=6.4, color=muted, height=12)
        c.setFont(normal, 7); c.setFillColor(HexColor(muted)); c.drawRightString(w-left, 24, f'{page} / 2')

    frame(1); y=h-88
    y=para(thesis['title'],left,y,size=25,height=68,strong=True)-12
    para(thesis['kind'].upper(),left,y,size=8,color=muted,height=15)
    para(f"{thesis['status'].upper()} / THESIS SCORE {thesis['score']:g}/100",right,y,width=col,size=8,color=red,height=25,strong=True)
    y-=38
    y=section('01 / Investment view',left,y)
    y=para(thesis['macro_thesis'],left,y,size=9.4,height=70)-9
    y=para(thesis['reason']+' '+thesis['forecast'],left,y,size=8.3,color=muted,height=39)-21
    y=section('02 / Economic transmission',left,y)
    chain=thesis.get('chain',[])[:5]
    for idx,step in enumerate(chain,1):
        para(f'{idx:02}',left,y,width=24,size=8,color=red,height=18,strong=True)
        yy=para(step,left+30,y,width=usable-30,size=9,height=27)
        y=yy-8
    y-=9
    y=section('03 / Macro evidence & observed trend',left,y)
    indicators=thesis.get('indicators',[])[:3]
    start=y
    for item in indicators:
        y=para(f"{item['name']}: {item['value']:g} {item['unit']}",left,y,width=col,size=8.4,height=26,strong=True)-3
        y=para(f"Period {item['observation_date']} / {item.get('frequency','')}"+(' / STALE' if item.get('stale') else ''),left,y,width=col,size=7.4,color=muted,height=23)-8
    if not indicators:
        y=para('data tidak ditemukan. Headline context does not establish quantitative confirmation.',left,y,width=col,size=8.4,color=muted,height=55)
    charts=[ch for ch in thesis.get('quantitative_charts',[]) if len(ch['points'])>=2]
    if charts:
        from datetime import date
        chart=charts[0]; points=chart['points']; vals=[p['value'] for p in points]
        low, high=min(vals),max(vals); span=high-low or 1
        cy=start-96; plotw=col-42; ploth=63
        para(chart['name']+' / '+chart['unit'],right,start,width=col,size=7.5,color=muted,height=24)
        c.setStrokeColor(HexColor(line)); c.line(right+34,cy,right+34+plotw,cy)
        dates=[date.fromisoformat(p['date']).toordinal() for p in points]; duration=dates[-1]-dates[0] or 1
        path=c.beginPath()
        for idx,(dt,value) in enumerate(zip(dates,vals)):
            xx=right+34+(dt-dates[0])/duration*plotw; yy=cy+(value-low)/span*ploth
            if idx: path.lineTo(xx,yy)
            else: path.moveTo(xx,yy)
        c.setStrokeColor(HexColor(red)); c.setLineWidth(1.3); c.drawPath(path)
        para(f'{high:,.1f}',right,cy+ploth+4,width=33,size=6.5,color=muted,height=13)
        para(f'{low:,.1f}',right,cy+5,width=33,size=6.5,color=muted,height=13)
        para(points[0]['date']+' - '+points[-1]['date'],right+34,cy-6,width=plotw,size=6.5,color=muted,height=12)
    else:
        para('Chart omitted: sufficient quantitative observations unavailable. No simulated series.',right,start,width=col,size=8,color=muted,height=65)
    y=min(y,start-119)-20
    y=section('04 / Beneficiary hypotheses & coverage',left,y)
    industries=sorted(thesis.get('industries',[]),key=lambda i:-i['score'])[:3]
    for item in industries:
        yy=para(item['industry'],left,y,width=col,size=10,height=18,strong=True)
        para(f"{item['score']:g}/100 | DATA {item['data_quality']:g}/100 | "+('ELIGIBLE' if item['eligible'] else 'MONITORING'),right,y,width=col,size=7.6,color=red if item['eligible'] else muted,height=20)
        y=yy-4
        y=para(item['earnings_effect'],left,y,size=8.3,height=25)-10
    if not industries: para('No verified beneficiary industry. Evidence remains insufficient.',left,y,size=9,height=28)

    c.showPage(); frame(2); y=h-89
    y=section('05 / Conviction, validation & risk',left,y)
    top=industries[0] if industries else None
    ly=ry=y
    if top:
        ly=para(top['industry']+' / WHY IT REMAINS A HYPOTHESIS' if not top['eligible'] else top['industry']+' / RESEARCH CONVICTION',left,ly,width=col,size=10,height=34,strong=True)-13
        for key in top.get('factors',{}):
            f=top.get('factors',{}).get(key)
            if not f:continue
            value='N/A' if f['value'] is None else f"{f['value']:g}/100"
            ly=para(f"{f['label']} / {value} / weight {f['weight']:g}%",left,ly,width=col,size=8,height=25,strong=True)-4
            ly=para(f['reason'],left,ly,width=col,size=8,color=muted,height=35)-10
        cv=top.get('coverage_confidence') or {}
        ly=para(f"Coverage: {cv.get('available_stocks','N/A')} of {cv.get('tracked_stocks','N/A')} tracked stocks; historical completeness {cv.get('historical_completeness','N/A')}%. Available scoring weight {top.get('coverage','N/A')}%.",left,ly,width=col,size=7.8,color=muted,height=46)-10
        market=top.get('market') or {}
        def pp(v):return 'N/A' if v is None else f'{v*100:+.2f} pp'
        ly=para(f"Relative return vs {market.get('benchmark','benchmark')}: 1M {pp(market.get('relative21'))}; 3M {pp(market.get('relative63'))}; 6M {pp(market.get('relative126'))}. Date {market.get('date','N/A')}.",left,ly,width=col,size=8,height=50)-10
        blockers=top.get('blockers',[])
        ly=para('Required: '+(' / '.join(blockers) or top['required_confirmation']),left,ly,width=col,size=8,height=65)
    else:
        ly=para('No eligible beneficiary. Establish representative coverage and macro confirmation before interpreting price moves as industry rotation.',left,ly,width=col,size=9,height=85)
    ry=para('SCENARIOS / CONDITIONAL, NOT PROBABILITIES',right,ry,width=col,size=8,color=red,height=26,strong=True)-12
    for name,text in thesis.get('scenarios',{}).items():
        ry=para(name.upper()+': '+text,right,ry,width=col,size=8.4,height=44)-10
    ry-=4; ry=section('Invalidation & monitoring',right,ry,width=col)
    for text in (thesis.get('invalidate',[])+thesis.get('checks',[]))[:4]:
        ry=para('- '+text,right,ry,width=col,size=8,height=35)-7
    ry-=6; ry=section('Adverse exposures',right,ry,width=col)
    for item in thesis.get('losers',[])[:2]:
        ry=para(item['industry']+': '+item['mechanism'],right,ry,width=col,size=8,height=39)-8
    ry-=7;ry=section('Source references',right,ry,width=col)
    sources=[(i['name']+' / '+i['observation_date'],i['source_url']) for i in thesis.get('indicators',[])]
    sources.extend((a['provider']+' / '+a['title'],a['url']) for a in thesis.get('evidence',[])[:3])
    sources.append(('Mechanism reference / not current confirmation',thesis['reference']))
    seen=set(); unique=[]
    for title,url in sources:
        if valid_url(url) and url not in seen:unique.append((title,url));seen.add(url)
    for idx,(title,url) in enumerate(unique[:4],1):
        before=ry;ry=para(f'[{idx}] '+title+'  [LINK]',right,ry,width=col,size=7.3,color=muted,height=24)-6
        c.linkURL(url,(right,ry+5,right+col,before),relative=0,thickness=0)
    y=min(ly,ry)-20
    # Reserve footer region for methodology; body excerpts are intentionally bounded.
    y=min(y,160)
    y=section('06 / Method & limitations',left,y)
    methodology=thesis.get('methodology')
    if methodology:
        weights=', '.join(f'{k} {v:g}%' for k,v in methodology['weights'].items())
        method='Macro-driven research weights: '+weights+'. Unavailable metrics excluded; remaining weights normalized. Coverage confidence is separate. One stock cannot establish industry rotation. Company fundamentals are not scoring inputs. Scores are research strength, not success probabilities. Combined macro model has not passed point-in-time validation.'
    else:
        method='Archived scoring methodology is preserved in this selected revision. Scores are thesis strength, not success probabilities. This report does not retroactively apply the current macro model.'
    para(method,left,y,size=7.6,color=muted,height=66)
    identifier=record.get('evaluation_id','')[:16]
    para(('Internal evaluation '+identifier+'. ' if draft else 'Exact selected published revision. ')+'Two-page editorial summary; complete reasons, sources and timestamps remain in the application. Export does not publish or notify.',left,68,size=6.6,color=muted,height=22)
    c.save(); return out.getvalue()
