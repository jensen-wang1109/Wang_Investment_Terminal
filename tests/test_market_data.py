import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from datetime import datetime,timezone
import pandas as pd
from services.research_api.market_data import normalize_history,instrument,last_completed_day,normalize_commodity,sync_market_history,cross_history
NOW=datetime(2026,10,22,8,tzinfo=timezone.utc)
class MarketDataTests(unittest.TestCase):
 def metadata(self):return {'symbol':'^GSPC','instrumentType':'INDEX','currency':'USD','exchangeTimezoneName':'America/New_York','currentTradingPeriod':{'regular':{'end':pd.Timestamp('2026-10-22T16:00:00-04:00')}}}
 def frame(self):return pd.DataFrame([{'Open':100.,'High':105.,'Low':99.,'Close':104.,'Adj Close':103.,'Volume':30}],index=pd.to_datetime(['2026-10-21']))
 def test_apple_or_wrong_instrument_type_is_never_accepted(self):
  for changes in [{'symbol':'AAPL'},{'instrumentType':'EQUITY'}]:
   meta={**self.metadata(),**changes}
   with self.assertRaisesRegex(ValueError,'identity'):normalize_history(instrument('^GSPC'),self.frame(),meta,NOW)
 def test_correct_ohlcv_is_preserved_and_source_timezone_controls_cutoff(self):
  points,rejected=normalize_history(instrument('^GSPC'),self.frame(),self.metadata(),NOW)
  self.assertEqual(rejected,0);self.assertEqual(points[0]['value'],104.);self.assertEqual(points[0]['adjusted_close'],103.)
  self.assertEqual(last_completed_day(self.metadata(),NOW),'2026-10-21')
  self.assertEqual(last_completed_day(self.metadata(),datetime(2026,10,22,21,tzinfo=timezone.utc)),'2026-10-22')
 def test_intraday_bar_rejected(self):
  frame=self.frame();frame.index=pd.to_datetime(['2026-10-22'])
  with self.assertRaisesRegex(ValueError,'completed'):normalize_history(instrument('^GSPC'),frame,self.metadata(),NOW)
 def test_stale_previous_close_does_not_finalize_todays_session(self):
  meta=self.metadata();meta['currentTradingPeriod']['regular']['end']=pd.Timestamp('2026-10-21T16:00:00-04:00')
  self.assertEqual(last_completed_day(meta,NOW),'2026-10-21')
 def test_invalid_ohlc_and_duplicate_sessions_rejected(self):
  frame=self.frame();frame.loc[:,'High']=99.
  with self.assertRaisesRegex(ValueError,'valid completed'):normalize_history(instrument('^GSPC'),frame,self.metadata(),NOW)
  with self.assertRaisesRegex(ValueError,'Duplicate'):normalize_history(instrument('^GSPC'),pd.concat([self.frame(),self.frame()]),self.metadata(),NOW)
 def test_currency_and_cotton_source_classification_are_explicit(self):
  with self.assertRaisesRegex(ValueError,'currency'):normalize_history(instrument('^GSPC'),self.frame(),{**self.metadata(),'currency':'JPY'},NOW)
  meta={**self.metadata(),'symbol':'CT=F','currency':'USX','instrumentType':'ALTSYMBOL'}
  self.assertEqual(len(normalize_history(instrument('CT=F'),self.frame(),meta,NOW)[0]),1)
 def test_commodity_cents_native_unit_and_timestamp_are_not_relabelled_as_usd_or_trade_session(self):
  row=normalize_commodity({'value':'wheat','currency_unit':'USX','unit':'bushel','price':500,'change_24h':-10,'updated':NOW.timestamp()},NOW)
  self.assertEqual(row['unit_label'],'USd/Bu');self.assertAlmostEqual(row['change_percent'],-1000/510)
  self.assertEqual(row['date_basis'],'source_update_not_certified_trade_date')
 def test_future_or_unrecognised_commodity_data_is_rejected(self):
  row={'value':'gold','currency_unit':'USD','unit':'troy_ounce','price':100,'updated':NOW.timestamp()}
  for changed in [{'price':float('nan')},{'updated':NOW.timestamp()+86400},{'unit':'unknown'},{'currency_unit':'unknown'}]:
   with self.assertRaises(ValueError):normalize_commodity({**row,**changed},NOW)
 def test_recent_stored_session_does_not_skip_incremental_source_refresh(self):
  cloud=Mock();cloud.latest_date.return_value=datetime.now(timezone.utc).date().isoformat()
  stored=[];cloud.ingest.side_effect=lambda series,points,run:stored.extend(points)
  cloud.history.side_effect=lambda series:stored
  ticker=Mock();ticker.history.return_value=self.frame();ticker.history_metadata=self.metadata()
  with tempfile.TemporaryDirectory() as directory,patch('yfinance.Ticker',return_value=ticker),patch('services.research_api.market_data.CACHE',Path(directory)),patch('services.research_api.market_data.time.sleep'):
   result=sync_market_history(cloud,['^GSPC'])
  ticker.history.assert_called_once();self.assertTrue(result['results'][0]['database_verified'])
 def test_fx_retains_verified_closing_rate_without_fabricating_bad_ohlc(self):
  frame=self.frame();frame['High']=101.
  spec={'symbol':'IDR=X','kind':'CURRENCY','currency':'IDR'};meta={**self.metadata(),'symbol':'IDR=X','instrumentType':'CURRENCY','currency':'IDR'}
  rows,rejected=normalize_history(spec,frame,meta,NOW)
  self.assertEqual(rows[0]['value'],104);self.assertIsNone(rows[0]['high']);self.assertIsNone(rows[0]['volume']);self.assertEqual(rejected,0)
 def test_cross_uses_only_matching_verified_completed_dates_and_correct_direction(self):
  import pandas as pd
  def ticker(symbol):
   close=18000 if symbol=='IDR=X' else 7.2
   frame=pd.DataFrame([{'Open':close,'High':close,'Low':close,'Close':close,'Volume':0}],index=pd.to_datetime(['2026-10-21']))
   t=Mock();t.history.return_value=frame;t.history_metadata={**self.metadata(),'symbol':symbol,'currency':'IDR' if symbol=='IDR=X' else 'CNY','instrumentType':'CURRENCY'};return t
  yf=Mock();yf.Ticker.side_effect=ticker
  rows,_=cross_history(instrument('CNYIDR=X'),yf,'2026-10-20','2026-10-23',NOW)
  self.assertEqual(rows[0]['value'],2500);self.assertEqual(rows[0]['quality_flag'],'derived_cross:CNYIDR=X');self.assertIsNone(rows[0]['open'])
if __name__=='__main__':unittest.main()
