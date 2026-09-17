import yfinance as yf
from yahooquery import Ticker
import requests
from datetime import datetime
import logging
import os
import threading
import time
import pandas as pd

logger = logging.getLogger(__name__)

STALE_HOURS = int(os.environ.get('FRESH_HOURS', 6))
REQUEST_DELAY = 0.4  # seconds between symbols to stay under Yahoo rate limits


class StockFetcher:
    def __init__(self, db, stocks):
        self.db = db
        self.stocks = stocks

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
        })

        self._fetch_lock = threading.Lock()

    def fetch_stock(self, symbol, force_refresh=False):
        """Fetch and store price history for one symbol. Returns record count."""
        with self._fetch_lock:
            if (not force_refresh and not self.db.is_stale(symbol, STALE_HOURS)):
                return self.db.count_prices(symbol)
            return self._fetch_locked(symbol)

    def _fetch_locked(self, symbol):
        logger.info(f"FETCH: {symbol} (yahooquery)")
        try:
            df = Ticker(symbol, session=self.session).history(
                period="6mo", interval="1d")
        except Exception as e:
            logger.warning(f"yahooquery failed for {symbol}: {e}")
            df = pd.DataFrame()

        if not isinstance(df, pd.DataFrame) or df.empty:
            logger.info(f"yfinance fallback for {symbol}")
            try:
                df = yf.download(
                    symbol, period="6mo", interval="1d",
                    progress=False, session=self.session)
            except Exception as e:
                logger.error(f"yfinance failed for {symbol}: {e}")
                return 0

        if df.empty:
            logger.warning(f"NO DATA ({symbol})")
            return 0

        prices = []
        if isinstance(df.index, pd.MultiIndex):
            df_reset = df.reset_index()
            for _, row in df_reset.iterrows():
                try:
                    price = float(row['close']) if 'close' in row else float(row['Close'])
                    if price > 0:
                        date_val = row['date'] if 'date' in df_reset.columns else row['Date']
                        date_str = (date_val.strftime('%Y-%m-%d')
                                    if hasattr(date_val, 'strftime')
                                    else str(date_val)[:10])
                        prices.append((date_str, price))
                except Exception:
                    continue
        else:
            close_col = (next((c for c in df.columns if c.lower() == 'close'), None)
                         or 'Close')
            for date, row in df.iterrows():
                try:
                    price = float(row[close_col])
                    if price > 0 and hasattr(date, 'strftime'):
                        prices.append((date.strftime('%Y-%m-%d'), price))
                except Exception:
                    continue

        if not prices:
            logger.warning(f"NO VALID PRICES ({symbol})")
            return 0

        self.db.save_prices(symbol, prices)
        self.db.set_last_fetched(symbol)
        logger.info(f"SAVED {len(prices)} days for {symbol}")
        return len(prices)

    def fetch_all(self, force_refresh=False):
        """Sweep the universe. Skips symbols fetched recently unless forced."""
        results = {}
        for symbol in self.stocks:
            if force_refresh or self.db.is_stale(symbol, STALE_HOURS):
                results[symbol] = self.fetch_stock(symbol, force_refresh=True)
            else:
                results[symbol] = self.db.count_prices(symbol)
            time.sleep(REQUEST_DELAY)
        return results

    def get_valuation(self, symbol):
        """Pull P/E, P/B and P/S ratios from Yahoo. Falls back to nulls."""
        try:
            # yfinance 1.2 requires its own curl_cffi session; don't pass ours.
            info = yf.Ticker(symbol).info or {}
        except Exception as e:
            logger.warning(f"Valuation failed for {symbol}: {e}")
            return {'pe': None, 'pb': None, 'ps': None}

        def num(v):
            try:
                v = float(v)
                return round(v, 2) if v == v else None  # drop NaN
            except (TypeError, ValueError):
                return None

        pe = num(info.get('trailingPE') or info.get('forwardPE'))
        pb = num(info.get('priceToBook'))
        ps = num(info.get('priceToSalesTrailing12Months'))
        return {'pe': pe, 'pb': pb, 'ps': ps}