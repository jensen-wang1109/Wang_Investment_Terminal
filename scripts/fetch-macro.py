"""Fetch public official macro files. No Google/Trading Economics scraping.

Raw responses are retained by checksum; each normalized release is reproducible.
Publication/availability timestamps stay unknown unless supplied by the source.
"""
import argparse
import csv
import hashlib
import io
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / '.private' / 'macro' / 'raw'
OUT = ROOT / 'public' / 'data' / 'macro-history.json'
WB_MONTHLY = 'https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx'

def finite(value):
    if value is None or str(value).strip() in ('', '.', '..', 'nan', 'NaN'):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None

def fetch(url, suffix):
    request = Request(url)
    with urlopen(request, timeout=20) as response:
        body = response.read(20 * 1024 * 1024 + 1)
        if len(body) > 20 * 1024 * 1024:
            raise ValueError('Source response exceeded 20 MB')
        modified = response.headers.get('Last-Modified')
    checksum = hashlib.sha256(body).hexdigest()
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f'{checksum}{suffix}').write_bytes(body)
    return body, checksum, modified

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', default=date.today().isoformat())
    args = parser.parse_args()
    cutoff = date.fromisoformat(args.as_of)
    retrieved = datetime.now(timezone.utc).isoformat()
    series, observations, sources, failures = [], [], [], []

    def register(key, label, unit, frequency, source, source_url, description, rows, checksum=None, source_modified=None):
        valid = sorted([row for row in rows if row[0] <= cutoff.isoformat()], key=lambda row: row[0])
        series.append({'id': key, 'label': label, 'unit': unit, 'frequency': frequency, 'source': source, 'sourceUrl': source_url, 'description': description, 'coverageStart': valid[0][0] if valid else None, 'coverageEnd': valid[-1][0] if valid else None, 'retrievedAt': retrieved, 'rawChecksum': checksum, 'publicationKnown': False})
        for period, value in valid:
            observations.append({'seriesId': key, 'date': period, 'value': value, 'retrievedAt': retrieved, 'publishedAt': None, 'availableAt': None, 'sourceUrl': source_url, 'rawChecksum': checksum})
        sources.append({'seriesId': key, 'url': source_url, 'sha256': checksum, 'retrievedAt': retrieved, 'sourceFileModifiedAt': source_modified})

    fred_specs = [
        ('fed', 'Fed target upper', '%', 'DFEDTARU'),
        ('fed_lower', 'Fed target lower', '%', 'DFEDTARL'),
        ('ust10', 'US Treasury 10Y', '%', 'DGS10'),
        ('ust2', 'US Treasury 2Y', '%', 'DGS2'),
        ('dollar_broad', 'US broad dollar index', 'index Jan 2006=100', 'DTWEXBGS'),
        ('wti', 'WTI spot, Cushing', 'USD / barrel', 'DCOILWTICO'),
        ('brent', 'Brent spot, Europe', 'USD / barrel', 'DCOILBRENTEU'),
    ]
    for key, label, unit, provider_id in fred_specs:
        fred_url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={provider_id}&cosd=2025-01-01'
        try:
            body, checksum, modified = fetch(fred_url, '.csv')
            table = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
            if not table or provider_id not in table[0]:
                raise ValueError('Unexpected FRED CSV columns')
            date_key = 'observation_date' if 'observation_date' in table[0] else 'DATE'
            register(key, label, unit, 'daily', 'FRED / original official agency', f'https://fred.stlouisfed.org/series/{provider_id}', 'Public CSV export. US broad dollar index is not DXY. Daily gaps remain unavailable.', [(row[date_key], finite(row[provider_id])) for row in table], checksum, modified)
        except Exception as error:
            failures.append({'provider': 'FRED', 'seriesId': key, 'error': str(error)})

    try:
        import pandas as pd
        body, checksum, modified = fetch(WB_MONTHLY, '.xlsx')
        excel = pd.ExcelFile(io.BytesIO(body))
        sheet_name = next(name for name in excel.sheet_names if 'Monthly' in name)
        raw = pd.read_excel(excel, sheet_name=sheet_name, header=None)
        header_index = next(i for i, row in raw.iterrows() if any(str(cell).strip() == 'Gold' for cell in row))
        headers = [str(cell).strip() for cell in raw.iloc[header_index]]
        print('World Bank columns:', ', '.join(headers[:18]))
        specs = [('gold', 'Gold', 'Gold', 'USD / troy oz'), ('coal', 'Coal (Australia)', 'Coal, Australian', 'USD / tonne'), ('coal_sa', 'Coal (South Africa)', 'Coal, South African **', 'USD / tonne'), ('cpo', 'Palm oil', 'Palm oil', 'USD / tonne'), ('nickel', 'Nickel', 'Nickel', 'USD / tonne'), ('copper', 'Copper', 'Copper', 'USD / tonne'), ('wti_monthly', 'WTI monthly average', 'Crude oil, WTI', 'USD / barrel'), ('brent_monthly', 'Brent monthly average', 'Crude oil, Brent', 'USD / barrel')]
        for key, label, column, unit in specs:
            if column not in headers:
                failures.append({'provider': 'World Bank', 'seriesId': key, 'error': f'Column absent: {column}'})
                continue
            column_index = headers.index(column)
            rows = []
            for _, row in raw.iloc[header_index + 1:].iterrows():
                period = str(row.iloc[0]).strip()
                if len(period) == 7 and period[4] == 'M' and period[:4].isdigit():
                    year, month = int(period[:4]), int(period[5:])
                    if year >= 2010 and 1 <= month <= 12:
                        # Monthly label represents that month, not daily spot data.
                        month_end = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
                        rows.append((month_end.date().isoformat(), finite(row.iloc[column_index])))
            register(key, label, unit, 'monthly', 'World Bank Pink Sheet', 'https://www.worldbank.org/en/research/commodity-markets', f'Monthly benchmark average: {column}. Not daily spot/futures. Attribute World Bank and original providers; check workbook definitions.', rows, checksum, modified)
    except Exception as error:
        failures.append({'provider': 'World Bank Pink Sheet', 'error': str(error)})

    for key, label, indicator, unit in [('id_gdp_annual', 'Indonesia GDP growth (annual)', 'NY.GDP.MKTP.KD.ZG', '% annual growth'), ('id_cpi_annual', 'Indonesia CPI inflation (annual average)', 'FP.CPI.TOTL.ZG', '% annual average')]:
        url = f'https://api.worldbank.org/v2/country/IDN/indicator/{indicator}?format=json&date=2010:{cutoff.year}&per_page=100'
        try:
            body, checksum, modified = fetch(url, '.json')
            data = json.loads(body)
            register(key, label, unit, 'annual', 'World Bank WDI', f'https://data.worldbank.org/indicator/{indicator}?locations=ID', 'Annual WDI context. Not quarterly GDP / monthly headline inflation; revisions possible.', [(f'{row["date"]}-12-31', finite(row['value'])) for row in data[1]], checksum, modified)
        except Exception as error:
            failures.append({'provider': 'World Bank WDI', 'seriesId': key, 'error': str(error)})

    # Source-reviewed official release snapshots, not automated BI/BPS scraping.
    reviewed_file = ROOT / 'data' / 'macro' / 'official-reviewed.json'
    if reviewed_file.exists():
        for item in json.loads(reviewed_file.read_text(encoding='utf-8')):
            register(item['id'], item['label'], item['unit'], item['frequency'], item['source'], item['sourceUrl'], item['description'], [(row['date'], row['value']) for row in item['observations']])

    if not any(item['rawChecksum'] for item in series):
        print(json.dumps({'failures': failures}, indent=2)); raise SystemExit('No official download succeeded; prior snapshot unchanged.')
    # A provider outage must not silently remove a previously available series.
    if OUT.exists():
        prior_manifest = json.loads(OUT.read_text(encoding='utf-8'))
        received_ids = {item['id'] for item in series}
        retained_ids = {item['id'] for item in prior_manifest['series'] if item['id'] not in received_ids}
        series.extend(item for item in prior_manifest['series'] if item['id'] in retained_ids)
        observations.extend(item for item in prior_manifest['observations'] if item['seriesId'] in retained_ids and item['date'] <= cutoff.isoformat())
        sources.extend(item for item in prior_manifest['sources'] if item['seriesId'] in retained_ids)
    manifest = {'schemaVersion': 1, 'generatedAt': retrieved, 'asOf': cutoff.isoformat(), 'series': series, 'observations': observations, 'sources': sources, 'failures': failures, 'pointInTimeBacktestReady': False}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        prior = OUT.read_bytes()
        (RAW / f'{hashlib.sha256(prior).hexdigest()}.normalized.json').write_bytes(prior)
    temporary = OUT.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(OUT)
    print(json.dumps({'series': len(series), 'observations': len(observations), 'failures': failures, 'latest': {item['id']: item['coverageEnd'] for item in series}}, indent=2))

if __name__ == '__main__':
    main()
