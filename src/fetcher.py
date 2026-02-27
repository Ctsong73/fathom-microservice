# src/fetcher.py
import yfinance as yf
import requests
from database import Database
from cache import StockCache
from datetime import datetime, timedelta
import logging
import time
import random

logger = logging.getLogger(__name__)

class StockFetcher:
    def __init__(self):
        self.db = Database()
        self.cache = StockCache(ttl=3600)
        self.stocks = ['C', 'XOM', 'NEM']
        
        # Create a session with a browser-like User-Agent
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
    
    def fetch_stock(self, symbol, force_refresh=False):
        """Fetch stock data using yfinance download and a custom session"""
        
        if not force_refresh:
            cached = self.cache.get_stock_data(symbol)
            if cached:
                logger.info(f"📦 Using cached data for {symbol}")
                return cached.get('count', 0)
        
        logger.info(f"🌐 FETCH START: {symbol} using yf.download with session...")
        
        try:
            # Use yf.download with the session for more robust bulk fetching
            # Fetch 6 months of data
            df = yf.download(
                symbol, 
                period="6mo", 
                interval="1d", 
                progress=False, 
                session=self.session
            )
            
            if df.empty:
                logger.warning(f"⚠️ FETCH FAILED: No data returned for {symbol}")
                return 0
            
            logger.info(f"📊 FETCH SUCCESS: {symbol} returned {len(df)} rows")
            
            # Prepare prices for database
            prices = []
            for date, row in df.iterrows():
                # Handle potential multi-index or single-index columns from yfinance
                try:
                    price = float(row['Close'])
                    if price is not None and price > 0:
                        date_str = date.strftime('%Y-%m-%d')
                        prices.append((date_str, price))
                except (KeyError, ValueError, TypeError) as e:
                    continue
            
            logger.info(f"🧹 DATA CLEANUP: {symbol} processed into {len(prices)} valid price points")
            
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
            
            logger.warning(f"⚠️ SAVE SKIPPED: No valid prices to save for {symbol}")
            return 0
            
        except Exception as e:
            logger.error(f"❌ ERROR fetching {symbol}: {e}", exc_info=True)
            return 0
    
    def fetch_all(self, force_refresh=False):
        results = {}
        for symbol in self.stocks:
            results[symbol] = self.fetch_stock(symbol, force_refresh)
        return results