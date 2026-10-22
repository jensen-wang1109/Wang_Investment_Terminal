"""Yahoo valuation table is authoritative for PBV; do not divide IDR by USD BVPS."""
from .providers import finite

def apply_price_book(details,frame,stamp):
    if frame is None or frame.empty:raise ValueError('Yahoo valuation table empty')
    columns=[c for c in frame.columns if str(c).strip().casefold()=='current']
    labels=[i for i in frame.index if str(i).strip().casefold()=='price/book']
    if len(columns)!=1 or len(labels)!=1:raise ValueError('Yahoo Current Price/Book not available')
    value=finite(frame.loc[labels[0],columns[0]])
    if value is None:raise ValueError('Yahoo Current Price/Book is missing')
    profile=details['profile'];metrics=details['metrics']
    provenance=dict(profile.get('metricProvenance') or {})
    old=provenance.get('priceToBook',{})
    raw=old.get('raw_info_value',metrics.get('priceToBook'))
    metrics['priceToBook']=value
    provenance['priceToBook']={'status':'verified_valuation_table','source':'Yahoo Finance',
        'field':'valuation.Price/Book.Current','source_url':'https://finance.yahoo.com/quote/'+profile['symbol']+'/key-statistics/',
        'retrieved_at':stamp,'raw_info_value':raw,'quote_currency':profile.get('currency'),
        'financial_currency':profile.get('financialCurrency'),'value':value,
        'note':'Direct Yahoo valuation ratio; no inferred FX conversion or IDR/USD division.'}
    profile['metricProvenance']=provenance
    return True

def protect_unverified_pbv(details):
    if details and details.get('profile',{}).get('metricProvenance',{}).get('priceToBook',{}).get('status')!='verified_valuation_table':
        details['metrics']={**details.get('metrics',{}),'priceToBook':None}
    if details:
        profile=details.get('profile',{})
        if profile.get('currency') and profile.get('financialCurrency') and profile['currency']!=profile['financialCurrency']:
            # Yahoo info also mixes IDR valuation numerators with USD sales/EBITDA.
            # Retain raw stored snapshots; suppress unverified derived fields on read.
            details['metrics']={**details.get('metrics',{}),**{k:None for k in ('enterpriseValue','priceToSalesTrailing12Months','enterpriseToRevenue','enterpriseToEbitda')}}
    return details
