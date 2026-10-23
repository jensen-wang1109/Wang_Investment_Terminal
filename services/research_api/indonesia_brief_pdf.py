"""Compact, two-page Indonesia daily brief using the exact persisted state."""
from io import BytesIO
from html import escape

def render_indonesia_brief(report):
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    out=BytesIO();ink=HexColor('#101012');muted=HexColor('#606068');red=HexColor('#D32938');rule=HexColor('#d8d8dc')
    body=ParagraphStyle('body',fontName='Helvetica',fontSize=9,leading=13,spaceAfter=7,textColor=ink)
    small=ParagraphStyle('small',parent=body,fontSize=7.5,leading=10,textColor=muted)
    heading=ParagraphStyle('heading',parent=body,fontName='Helvetica-Bold',fontSize=12,leading=16,spaceBefore=12,spaceAfter=8,keepWithNext=True)
    title=ParagraphStyle('title',parent=heading,fontSize=24,leading=28,spaceBefore=2,spaceAfter=14)
    label=ParagraphStyle('label',parent=small,textColor=red,fontName='Helvetica-Bold')
    def clean(x):return escape(str(x if x is not None else 'data tidak ditemukan').replace('→',' / ').replace('–','-').replace('—','-').replace('−','-').replace('×','x'))
    def p(x,style=body):return Paragraph(clean(x),style)
    def percent(x):return f'{x*100:+.2f}%' if x is not None else 'N/A'
    b=report['brief'];doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=44,rightMargin=44,topMargin=54,bottomMargin=44,title='Indonesia Macro & Market Intelligence',author='Wang Investment Terminal')
    def footer(c,d):
        c.saveState();c.setStrokeColor(rule);c.line(44,810,551,810);c.line(44,31,551,31);c.setFont('Helvetica-Bold',8);c.setFillColor(red);c.drawString(44,820,'WANG / INVESTMENT INTELLIGENCE');c.setFont('Helvetica',7);c.setFillColor(muted);c.drawString(44,20,report['report_date']+' | Private research | Research scores are not return probabilities');c.drawRightString(551,20,str(d.page));c.restoreState()
    story=[p('DAILY INDONESIA BRIEF / '+report['report_date'],label),p('Indonesia Macro &\nMarket Intelligence'.replace('\n',' '),title),p('A / MACRO & MARKET REGIME',heading)]
    cells=[]
    for key,name in [('economic_regime','INDONESIA ECONOMY'),('equity_regime','IHSG MARKET')]:
        r=b[key];cells.append([p(name,label),p(r['current'],heading),p('Previous: '+str(r['previous'] or 'Initial baseline')+' | confidence '+r['confidence'],small),p('Candidate: '+r['candidate']+' | persistence '+str(r['persistence'])+' day(s)',small)])
    table=Table([[cells[0],cells[1]]],colWidths=[253,254]);table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,-1),HexColor('#f3f3f4')),('BOX',(0,0),(-1,-1),.5,rule),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),8)]));story.append(table)
    story += [p('B / EXECUTIVE SUMMARY',heading),p(b['executive_summary']),p('C / WHAT CHANGED TODAY?',heading)]
    if not b['changes']:story += [p(b['change_message']),p(b['baseline_status'],small)]
    for c in b['changes'][:5]:
        story.append(KeepTogether([p(c['title'],label),p(f"{c['previous']['value']} ({c['previous']['date'] or 'baseline absent'}) / {c['current']['value']} ({c['current']['date']}). "+c['why'],small)]))
    if b.get('non_trading_day'):story.append(p('Non-trading day: latest valid observations retained; no new market session inferred.',small))
    story += [PageBreak(),p('D / IHSG & RUPIAH OUTLOOK',heading),p('Evaluation horizon: 1-4 weeks. Observed direction is separate from macro-supported outlook.',small)]
    for key,name in [('ihsg','IHSG'),('rupiah','RUPIAH')]:
        m=b[key];story += [p(name+' / '+m['outlook'],label),p(f"Last observation: {m['last_date'] or 'N/A'} | status: {m['status']} | 5 sessions: {percent(m['returns'].get('5'))} | 20 sessions: {percent(m['returns'].get('20'))}",small)]
        if key=='ihsg':story.append(p('Macro-supported outlook: '+m['macro_supported_outlook']+'. '+m['conflicts'][0],small))
        else:story.append(p('Higher USD/IDR means weaker rupiah. '+m['uncertainty'],small))
        story.append(p('Invalidation: '+m['invalidation'],small))
    story += [p('E / INVESTMENT IMPLICATIONS',heading)]
    for direction,name in [('potential_beneficiary','Conditional beneficiaries'),('potential_risk','Conditional risks')]:
        items=[i for i in b['industry_impacts'] if i['direction']==direction][:3]
        story.append(p(name,label))
        for item in items:story.append(p(item['industry']+': '+item['condition'],small))
        if not items:story.append(p('Insufficient verified evidence for a defensible industry conclusion.',small))
    story += [p('Monitor: '+'; '.join(b['monitor']),small),p('EVIDENCE & RESEARCH LIMITS',heading),p('Missing inputs: '+', '.join(b['missing_inputs'])+'. Macroeconomic release vintages remain incomplete. Heuristic conviction weights are provisional; no validated return probabilities, exact targets or claimed out-of-sample forecasting accuracy.',small)]
    refs={}
    for m in (b['ihsg'],b['rupiah']):
        for d in m['drivers']:refs[d['source_url']]=d['name']+' / '+d['date']
    for e in b['events']:
        if e['materiality']=='HIGH':
            for r in e['references']:refs[r['url']]=r['title'][:95]
    for url,name in list(refs.items())[:7]:
        if url.startswith('https://'):story.append(Paragraph(clean(name)+' / <link href="'+escape(url,quote=True)+'" color="#D32938">source</link>',small))
    story.append(p('Shared state: '+report['shared_analysis_id'][:16]+' | '+b['version']+' | retrieved '+report['knowledge_cutoff'],small))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
