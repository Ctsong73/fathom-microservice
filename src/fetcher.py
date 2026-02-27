# src/fetcher.py
import yfinance as yf
from yahooquery import Ticker
import requests
from database import Database
from cache import StockCache
from datetime import datetime, timedelta
import logging
import time
import pandas as pd

logger = logging.getLogger(__name__)

class StockFetcher:
    def __init__(self):
        self.db = Database()
        self.cache = StockCache(ttl=3600)
        self.stocks = ['C', 'XOM', 'NEM']
        
        # Create a session for yfinance fallback
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    def fetch_stock(self, symbol, force_refresh=False):
        """Fetch stock data using yahooquery (primary) and yfinance (fallback)"""
        
        if not force_refresh:
            cached = self.cache.get_stock_data(symbol)
            if cached:
                logger.info(f"📦 Using cached data for {symbol}")
                return cached.get('count', 0)
        
        logger.info(f"🌐 FETCH START: {symbol} using yahooquery...")
        
        try:
            # Try yahooquery first
            t = Ticker(symbol, session=self.session)
            df = t.history(period="6mo", interval="1d")
            
            # yahooquery returns a multi-index (symbol, date) if symbol passed as string
            # or a single index if processed correctly. Let's process it.
            if isinstance(df, pd.DataFrame) and not df.empty:
                logger.info(f"📊 FETCH SUCCESS (yahooquery): {symbol} returned {len(df)} rows")
            else:
                logger.warning(f"⚠️ yahooquery failed or returned empty for {symbol}. Trying yf.download fallback...")
                df = yf.download(
                    symbol, 
                    period="6mo", 
                    interval="1d", 
                    progress=False, 
                    session=self.session
                )
            
            if df.empty:
                logger.warning(f"❌ ALL FETCH METHODS FAILED for {symbol}")
                return 0
            
            # Prepare prices for database
            prices = []
            
            # yahooquery often has a MultiIndex (symbol, date)
            # yfinance has a single DatetimeIndex
            if isinstance(df.index, pd.MultiIndex):
                # Reset index to get 'date' as a column
                df_reset = df.reset_index()
                # Find the date column (might be named 'date' or 'Date')
                date_col = 'date' if 'date' in df_reset.columns else 'Date'
                for _, row in df_reset.iterrows():
                    try:
                        price = float(row['close']) if 'close' in row else float(row['Close'])
                        if price > 0:
                            date_val = row[date_col]
                            date_str = date_val.strftime('%Y-%m-%d') if hasattr(date_val, 'strftime') else str(date_val)[:10]
                            prices.append((date_str, price))
                    except: continue
            else:
                # Single index (likely yfinance or flattened yahooquery)
                for date, row in df.iterrows():
                    try:
                        # Case insensitive check for Close
                        close_col = next((c for c in df.columns if c.lower() == 'close'), None)
                        if close_col:
                            price = float(row[close_col])
                            if price > 0:
                                date_str = date.strftime('%Y-%m-%d')
                                prices.append((date_str, price))
                    except: continue
            
            logger.info(f"🧹 DATA CLEANUP: {symbol} processed into {len(prices)} valid points")
            
            if prices:
                # Log a few samples for debugging
                logger.info(f"📝 SAMPLE DATA ({symbol}): First: {prices[0]}, Last: {prices[-1]}")
                
                self.db.save_prices(symbol, prices)
                self.db.cleanup_old_data()
                
                result = {
                    'symbol': symbol, 
                    'count': len(prices), 
                    'timestamp': datetime.now().isoformat()
                }
                self.cache.set_stock_data(symbol, result)
                self.cache.invalidate_stock(symbol)
                
                logger.info(f"✅ SAVE COMPLETE: {len(prices)} days stored for {symbol}")
                return len(prices)
            
            return 0
            
        except Exception as e:
            logger.error(f"❌ ERROR fetching {symbol}: {e}", exc_info=True)
            return 0
    
    def fetch_all(self, force_refresh=False):
        results = {}
        for symbol in self.stocks:
            results[symbol] = self.fetch_stock(symbol, force_refresh)
        return results