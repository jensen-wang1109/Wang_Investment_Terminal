"""User-requested personal EOD downloads. No frontend I/O or ML permission claim."""
from datetime import datetime,timezone
import importlib
from .contracts import DailyPrice
from .providers import finite,provider_symbol,retry_transient

class YahooEodProvider:
    def __init__(self,loader=importlib.import_module):self.loader=loader

    def first_trade_date(self,instrument):
        metadata=retry_transient(lambda:self.loader('yfinance').Ticker(provider_symbol(instrument)).get_history_metadata())
        epoch=metadata.get('firstTradeDate') if metadata else None
        if epoch is None:return None
        from zoneinfo import ZoneInfo
        if isinstance(epoch,datetime):return epoch.astimezone(ZoneInfo(instrument.timezone)).date().isoformat()
        if isinstance(epoch,str):return datetime.fromisoformat(epoch.replace('Z','+00:00')).astimezone(ZoneInfo(instrument.timezone)).date().isoformat()
        return datetime.fromtimestamp(epoch,timezone.utc).astimezone(ZoneInfo(instrument.timezone)).date().isoformat()

    def history(self,instrument,start,end):
        library=self.loader('yfinance')
        # Explicit raw OHLC and separate Adj Close; end is exclusive in yfinance.
        frame=retry_transient(lambda:library.download(provider_symbol(instrument),start=start,end=end,
            interval='1d',auto_adjust=False,actions=False,threads=False,progress=False,
            multi_level_index=False,timeout=30))
        if frame is None or frame.empty:raise ValueError('Yahoo returned no daily prices; existing history preserved')
        required={'Open','High','Low','Close','Volume'}
        if not required.issubset(frame.columns):raise ValueError('Yahoo response lacks required OHLCV columns')
        fetched=datetime.now(timezone.utc).isoformat();result=[]
        for timestamp,row in frame.iterrows():
            volume=finite(row.get('Volume'))
            if volume is None or volume<0 or not volume.is_integer():raise ValueError('Invalid source volume')
            day=timestamp.tz_convert(instrument.timezone).date() if timestamp.tzinfo is not None else timestamp.date()
            result.append(DailyPrice(instrument.symbol,day.isoformat(),finite(row['Open']),finite(row['High']),
                finite(row['Low']),finite(row['Close']),finite(row.get('Adj Close')),int(volume),
                instrument.currency,'yahoo',fetched))
        return result
