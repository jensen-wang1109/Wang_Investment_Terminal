import csv
import hashlib
import io
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from .contracts import PermissionDenied
from .rights import require_rights


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class ResearchRepository:
    def __init__(self, file):
        self.file = Path(file)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            create table if not exists sources(id text primary key,provider text not null,source_url text not null,rights_basis text not null,review_status text not null);
            create table if not exists prices(id integer primary key,source_id text not null references sources(id),symbol text not null,observation_date text not null,open real,high real,low real,close real,adjusted_close real,volume integer,currency text not null,available_at text,is_final integer not null,fetched_at text not null,row_hash text not null,unique(source_id,symbol,observation_date,row_hash));
            create index if not exists price_lookup on prices(symbol,observation_date,id);
            create table if not exists jobs(id integer primary key,status text not null,started_at text not null,finished_at text,row_count integer not null default 0,inserted integer not null default 0,message text);
            create table if not exists quality_logs(id integer primary key,job_id integer references jobs(id),severity text not null,code text not null,message text not null);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.file)
        db.execute('pragma foreign_keys=on')
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_csv(self, text, source):
        if not isinstance(source, dict) or source.get('provider') not in ('user_owned','licensed','official_download','yahoo'):
            raise ValueError('Specify the original source provider: user_owned, licensed, official_download or yahoo')
        if source['provider'] == 'yahoo':
            require_rights('yahoo','retain')
        if source.get('retain_allowed') is not True or not str(source.get('rights_basis','')).strip() or not str(source.get('source_url','')).startswith('https://'):
            raise PermissionDenied('Manual import requires retention attestation, source URL and a rights basis; this is not ML permission')
        started = now_iso()
        with self.connect() as db:
            job_id = db.execute('insert into jobs(status,started_at) values (?,?)',('validating',started)).lastrowid
        try:
            rows = self.validate_csv(text)
            source_id = hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
            inserted = 0
            with self.connect() as db:
                for row in rows:
                    existing = db.execute('select currency from prices where symbol=? and currency<>? limit 1',(row['symbol'],row['currency'])).fetchone()
                    if existing:
                        raise ValueError('Currency conflicts with existing history for '+row['symbol'])
                db.execute('insert or ignore into sources values (?,?,?,?,?)',(source_id,source['provider'],source['source_url'],source['rights_basis'],'user_attested'))
                for row in rows:
                    digest = hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
                    inserted += db.execute('insert or ignore into prices(source_id,symbol,observation_date,open,high,low,close,adjusted_close,volume,currency,available_at,is_final,fetched_at,row_hash) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (source_id,row['symbol'],row['observation_date'],row['open'],row['high'],row['low'],row['close'],row['adjusted_close'],row['volume'],row['currency'],row['available_at'],row['is_final'],started,digest)).rowcount
                db.execute('update jobs set status=?,finished_at=?,row_count=?,inserted=? where id=?',('complete',now_iso(),len(rows),inserted,job_id))
                missing = sum(row['close'] is None for row in rows)
                if missing:
                    db.execute('insert into quality_logs(job_id,severity,code,message) values (?,?,?,?)',(job_id,'warning','missing_close',str(missing)+' observations have no close; retained as null'))
            return {'job_id':job_id,'status':'complete','rows':len(rows),'inserted':inserted,'duplicates':len(rows)-inserted,'source_review':'user_attested','training_allowed':False}
        except Exception as error:
            with self.connect() as db:
                db.execute('update jobs set status=?,finished_at=?,message=? where id=?',('failed',now_iso(),str(error)[:500],job_id))
                db.execute('insert into quality_logs(job_id,severity,code,message) values (?,?,?,?)',(job_id,'error','import_rejected',str(error)[:500]))
            raise

    @staticmethod
    def validate_csv(text):
        if not isinstance(text,str) or len(text.encode())>2*1024*1024:
            raise ValueError('CSV must be UTF-8 text up to 2 MB')
        reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
        required = {'symbol','observation_date','open','high','low','close','volume','currency'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames) or len(reader.fieldnames)!=len(set(reader.fieldnames)):
            raise ValueError('CSV headers must include: '+','.join(sorted(required)))
        rows, keys, units = [], set(), {}
        for index, raw in enumerate(reader,2):
            if index>20001 or None in raw or any(value is None for value in raw.values()):
                raise ValueError(f'Row {index}: CSV row length or limit is invalid')
            symbol = raw['symbol'].strip().upper()
            if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=-]{0,19}',symbol):
                raise ValueError(f'Row {index}: invalid ticker')
            observed = date.fromisoformat(raw['observation_date'])
            if observed > datetime.now(timezone.utc).date():
                raise ValueError(f'Row {index}: future observation')
            key = (symbol,observed.isoformat())
            if key in keys:
                raise ValueError(f'Row {index}: duplicate symbol/date within file; resolve revisions before import')
            keys.add(key)
            currency = raw['currency'].strip().upper()
            if not re.fullmatch('[A-Z]{3}',currency) or symbol.endswith('.JK') and currency!='IDR' or symbol in units and units[symbol]!=currency:
                raise ValueError(f'Row {index}: currency mismatch')
            units[symbol] = currency
            row = {'symbol':symbol,'observation_date':observed.isoformat(),'currency':currency}
            for field in ('open','high','low','close','adjusted_close','volume'):
                value = raw.get(field,'').strip()
                number = float(value) if value else None
                if number is not None and (not math.isfinite(number) or number<0 or number>10**15 or field=='volume' and not number.is_integer()):
                    raise ValueError(f'Row {index}: invalid {field}')
                row[field] = int(number) if field=='volume' and number is not None else number
            if row['high'] is not None and row['low'] is not None:
                if row['high']<row['low'] or any(row[field] is not None and not row['low']<=row[field]<=row['high'] for field in ('open','close')):
                    raise ValueError(f'Row {index}: OHLC bounds inconsistent')
            available = raw.get('available_at','').strip()
            if available:
                instant = datetime.fromisoformat(available.replace('Z','+00:00'))
                if instant.tzinfo is None or instant > datetime.now(timezone.utc):
                    raise ValueError(f'Row {index}: availability must be a known past timestamp with timezone')
                local_day = instant.astimezone(timezone(timedelta(hours=7)) if symbol.endswith('.JK') else timezone.utc).date()
                if local_day < observed:
                    raise ValueError(f'Row {index}: availability precedes the observation date')
                available = instant.isoformat()
            final = raw.get('is_final','false').strip().lower()
            if final not in ('true','false','1','0',''):
                raise ValueError(f'Row {index}: invalid is_final')
            row.update(available_at=available or None,is_final=final in ('true','1'))
            rows.append(row)
        if not rows:
            raise ValueError('CSV has no observations')
        return rows

    def prices(self, symbol=None):
        with self.connect() as db:
            rows = db.execute('''with current as (select p.*,row_number() over(partition by source_id,symbol,observation_date order by id desc) revision from prices p)
              select c.*,s.provider,s.source_url,s.review_status from current c join sources s on s.id=c.source_id where revision=1 and (? is null or symbol=?) order by symbol,observation_date''',(symbol,symbol)).fetchall()
        return [dict(row) for row in rows]

    def ledger(self):
        with self.connect() as db:
            return {'jobs':[dict(row) for row in db.execute('select * from jobs order by id desc limit 20')], 'quality_logs':[dict(row) for row in db.execute('select * from quality_logs order by id desc limit 50')]}

    def export_csv(self, symbol=None):
        output = io.StringIO()
        fields = ['symbol','observation_date','open','high','low','close','adjusted_close','volume','currency','available_at','is_final','provider','source_url','fetched_at','review_status']
        writer = csv.DictWriter(output,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in self.prices(symbol):
            row['is_final'] = bool(row['is_final'])
            writer.writerow(row)
        return output.getvalue()
