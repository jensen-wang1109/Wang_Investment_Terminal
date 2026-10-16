"""Optional yfinance integration. Rights are checked before import or I/O."""
from datetime import datetime, timezone
import importlib
import math
import time
from .contracts import DailyPrice, InstrumentRef, UnsupportedCapability
from .rights import require_rights


def provider_symbol(instrument: InstrumentRef):
    if instrument.exchange == 'IDX':
        raw = instrument.symbol.removesuffix('.JK').upper()
        if not raw.isalnum() or not 3 <= len(raw) <= 10:
            raise ValueError('Invalid IDX ticker')
        return raw + '.JK'
    if instrument.exchange in ('NASDAQ', 'NYSE', 'INDEX'):
        return instrument.symbol
    raise UnsupportedCapability('Exchange mapping has not been reviewed')


def retry_transient(call, attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return call()
        except Exception as error:
            status = getattr(error, 'status_code', getattr(error,'code',None))
            if status is None:status=getattr(getattr(error,'response',None),'status_code',None)
            transient=isinstance(error,(TimeoutError,ConnectionError)) or error.__class__.__name__ in ('Timeout','ConnectTimeout','ReadTimeout','ConnectionError')
            if status in (401,403,429) or (status not in (500, 502, 503, 504) and not transient):
                raise
            if attempt == attempts - 1:
                raise
            sleep(min(2 ** attempt, 8))


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


class YahooProvider:
    name = 'yahoo'
    def __init__(self, rights_path=None, loader=importlib.import_module):
        self.rights_path, self.loader = rights_path, loader

    def _ticker(self, instrument):
        require_rights(self.name, 'retrieve', 'cache', path=self.rights_path)
        try:
            library = self.loader('yfinance')
        except ImportError as error:
            raise UnsupportedCapability('Optional yfinance dependency is not installed; see setup instructions') from error
        return library.Ticker(provider_symbol(instrument))

    def history(self, instrument, start, end):
        ticker = self._ticker(instrument)
        frame = retry_transient(lambda: ticker.history(start=start, end=end, interval='1d', auto_adjust=False, actions=True, raise_errors=True))
        fetched = datetime.now(timezone.utc).isoformat()
        result = []
        for timestamp, row in frame.iterrows():
            close, volume = finite(row.get('Close')), finite(row.get('Volume'))
            if volume is not None and (volume < 0 or not volume.is_integer()):
                raise ValueError('Invalid source volume')
            result.append(DailyPrice(instrument.symbol, timestamp.date().isoformat(), finite(row.get('Open')), finite(row.get('High')), finite(row.get('Low')), close, finite(row.get('Adj Close')), int(volume) if volume is not None else None, instrument.currency, self.name, fetched, dividend=finite(row.get('Dividends')), split_ratio=finite(row.get('Stock Splits'))))
        return result

    def latest(self, instrument):
        info = retry_transient(lambda: self._ticker(instrument).get_info())
        return {'symbol': instrument.symbol, 'price': finite(info.get('regularMarketPrice')), 'currency': info.get('currency'), 'provider': self.name, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'quote_timestamp': info.get('regularMarketTime'), 'delay_status': 'provider_delay_not_verified'}

    def company(self, instrument):
        info = retry_transient(lambda: self._ticker(instrument).get_info())
        return {key: info.get(key) for key in ('longName', 'longBusinessSummary', 'sector', 'industry', 'website', 'currency')}

    def classification(self, instrument):
        info = self.company(instrument)
        return {'sector': info.get('sector'), 'industry': info.get('industry'), 'taxonomy': 'Yahoo vendor classification; not IDX-IC'}

    def statements(self, instrument):
        return self.details(instrument)['statements']

    def details(self, instrument):
        from .stock_details import collect_details
        return collect_details(self._ticker(instrument))

    def actions(self, instrument, start, end):
        from .stock_details import actions_from_bars
        return actions_from_bars(self.history(instrument,start,end))

    def index_history(self, instrument, start, end):
        return self.history(instrument, start, end)

    def indicators(self, identifiers, start, end):
        require_rights(self.name, 'retrieve', path=self.rights_path)
        raise UnsupportedCapability('Macro/commodity mappings and units require individual source review')
