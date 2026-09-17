import yfinance as yf
from yahooquery import Ticker
import requests
from datetime import datetime
import logging
import os
import threading
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

STALE_HOURS = int(os.environ.get('FRESH_HOURS', 6))
REQUEST_DELAY = 0.6  # seconds between symbols to stay under Yahoo rate limits
VALUATION_RETRIES = 4  # attempts for valuation (Yahoo throttles around boot sync)


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
        self._update_momentum(symbol)
        logger.info(f"SAVED {len(prices)} days for {symbol}")
        return len(prices)

    def _update_momentum(self, symbol):
        """Recompute and store the 6-month momentum % from stored closes."""
        closes = [p[1] for p in self.db.get_prices(symbol, days=180)]
        if len(closes) >= 2:
            m6 = (closes[-1] / closes[0] - 1) * 100
            self.db.set_momentum(symbol, round(m6, 2))

    def refresh_metadata(self, stocks=None):
        """Refresh market caps for the universe (parallel, light quote calls)."""
        stocks = stocks or self.stocks
        results = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(self._market_cap_one, s): s for s in stocks}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as e:
                    logger.warning(f"Metadata failed for {symbol}: {e}")
                    results[symbol] = None
        return results

    def _market_cap_one(self, symbol):
        cap = yf.Ticker(symbol).fast_info['market_cap']
        if cap:
            self.db.set_market_cap(symbol, float(cap))
            return float(cap)
        return None

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

    def get_snapshot(self, symbol):
        """Pull valuation ratios + market cap / 52wk range / volume from Yahoo."""
        # yfinance 1.2 requires its own curl_cffi session; don't pass ours.
        def num(v):
            try:
                v = float(v)
                return round(v, 2) if v == v else None  # drop NaN
            except (TypeError, ValueError):
                return None

        empty = {'pe': None, 'pb': None, 'ps': None,
                 'market_cap': None, 'week52_low': None, 'week52_high': None,
                 'volume': None, 'avg_volume': None}

        # Yahoo throttles the snapshot endpoint right after boot sync, so
        # back off a little between attempts instead of giving up instantly.
        for attempt in range(VALUATION_RETRIES):
            try:
                info = yf.Ticker(symbol).info or {}
            except Exception as e:
                logger.warning(f"Snapshot failed for {symbol} (try {attempt + 1}): {e}")
                if attempt < VALUATION_RETRIES - 1:
                    time.sleep(2)
                continue
            pe = num(info.get('trailingPE') or info.get('forwardPE'))
            pb = num(info.get('priceToBook'))
            ps = num(info.get('priceToSalesTrailing12Months'))
            market_cap = num(info.get('marketCap'))
            week52_low = num(info.get('fiftyTwoWeekLow'))
            week52_high = num(info.get('fiftyTwoWeekHigh'))
            volume = num(info.get('regularMarketVolume'))
            avg_volume = (num(info.get('averageVolume'))
                          or num(info.get('averageDailyVolume3Month')))
            snap = {'pe': pe, 'pb': pb, 'ps': ps,
                    'market_cap': market_cap,
                    'week52_low': week52_low, 'week52_high': week52_high,
                    'volume': volume, 'avg_volume': avg_volume}
            if any(v is not None for v in snap.values()):
                return snap
            if attempt < VALUATION_RETRIES - 1:
                time.sleep(2)
        logger.warning(f"Snapshot unavailable for {symbol}")
        return empty

    def debug_valuation(self, symbol):
        """Diagnose what Yahoo actually returns for valuation (debug only)."""
        out = {'symbol': symbol}
        try:
            t = yf.Ticker(symbol)
            out['has_get_info'] = hasattr(t, 'get_info')
            info = yf.Ticker(symbol).info or {}
            out['info'] = info
        except Exception as e:
            out['exception'] = repr(e)
            return out
        keys = ('trailingPE', 'forwardPE', 'priceToBook',
                'priceToSalesTrailing12Months')
        out['values'] = {k: info.get(k) for k in keys}
        out['key_count'] = len(info)
        return out