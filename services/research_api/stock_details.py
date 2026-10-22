"""Vendor snapshots retain units, periods, nulls and original statement labels.

They are observations at retrieval time, not point-in-time filing vintages.
"""
from datetime import datetime, timezone
import time
from .providers import finite, retry_transient

INFO_METRICS = (
    'marketCap','trailingPE','forwardPE','priceToBook','trailingEps','forwardEps',
    'bookValue','returnOnEquity','returnOnAssets','totalRevenue','netIncomeToCommon',
    'ebitda','operatingCashflow','freeCashflow','totalCash','totalDebt',
    'enterpriseValue','enterpriseToRevenue','enterpriseToEbitda','priceToSalesTrailing12Months',
    'profitMargins','grossMargins','operatingMargins','ebitdaMargins','revenueGrowth','earningsGrowth',
    'earningsQuarterlyGrowth','revenuePerShare','totalCashPerShare','debtToEquity','currentRatio','quickRatio',
    'sharesOutstanding','impliedSharesOutstanding','floatShares','heldPercentInsiders','heldPercentInstitutions',
    'beta','fiftyTwoWeekLow','fiftyTwoWeekHigh','fiftyDayAverage','twoHundredDayAverage',
    'averageVolume','averageVolume10days','dividendRate','dividendYield','trailingAnnualDividendRate',
    'trailingAnnualDividendYield','fiveYearAvgDividendYield','payoutRatio','lastDividendValue',
    'targetHighPrice','targetLowPrice','targetMeanPrice','targetMedianPrice','recommendationMean','numberOfAnalystOpinions',
)

def normalize_info(info):
    if not isinstance(info,dict) or not any(info.get(k) for k in ('longName','shortName','symbol')):
        raise ValueError('Empty company information from provider')
    def string(key):
        value=info.get(key)
        return value if isinstance(value,str) and value.strip() else None
    return {
        'profile':{**{key:string(key) for key in ('longName','shortName','symbol','longBusinessSummary','sector','industry','website','currency','financialCurrency','exchange','address1','address2','city','state','zip','country','phone','recommendationKey')},'fullTimeEmployees':finite(info.get('fullTimeEmployees'))},
        'metrics':{key:finite(info.get(key)) for key in INFO_METRICS},
        'basis':'Yahoo info snapshot; trailing/forward and quote/reporting currencies remain separate',
        'published_at':None,'available_at':None,
    }

def normalize_statement(frame,kind,frequency,currency,as_of=None):
    result=[]
    if frame is None or frame.empty:return result
    for column in frame.columns:
        day=column.date().isoformat()
        if as_of:
            from datetime import date
            end=date.fromisoformat(day);cutoff=as_of.date() if hasattr(as_of,'date') else as_of
            try:start=cutoff.replace(year=cutoff.year-5)
            except ValueError:start=cutoff.replace(year=cutoff.year-5,day=28)
            if not start<=end<=cutoff:continue
        values={str(label):finite(value) for label,value in frame[column].items()}
        if not any(value is not None for value in values.values()):continue
        result.append({'statement_kind':kind,'frequency':frequency,'period_end':day,
                       'currency':currency,'line_items':values,'published_at':None,'available_at':None})
    return result

def collect_details(ticker,sleep=time.sleep):
    info=retry_transient(ticker.get_info)
    result=normalize_info(info)
    stamp=datetime.now(timezone.utc).isoformat()
    try:
        from .yahoo_valuation import apply_price_book
        apply_price_book(result,ticker.valuation,stamp)
    except Exception as error:
        from .providers import access_status
        if access_status(error) in (401,403,429):raise
        result['metrics']['priceToBook']=None
    statements=[]
    for kind,method in (('income',ticker.get_income_stmt),('balance',ticker.get_balance_sheet),('cashflow',ticker.get_cashflow)):
        for frequency in ('yearly','quarterly'):
            sleep(1)
            frame=retry_transient(lambda:method(freq=frequency,pretty=False))
            statements.extend(normalize_statement(frame,kind,frequency,info.get('financialCurrency'),datetime.now(timezone.utc)))
    result['statements']=statements
    result['retrieved_at']=datetime.now(timezone.utc).isoformat()
    return result

def actions_from_bars(bars):
    result=[]
    for bar in bars:
        for kind,value in (('dividend',bar.dividend),('split',bar.split_ratio)):
            if value is not None and value>0:
                result.append({'event_date':bar.observation_date,'action_kind':kind,'value':value,
                               'currency':bar.currency if kind=='dividend' else None,
                               'retrieved_at':bar.fetched_at,'published_at':None})
    return result
