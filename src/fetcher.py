# src/fetcher.py
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
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_stock(self, symbol, force_refresh=False):
        """Fetch stock data directly from Yahoo Finance API"""
        
        if not force_refresh:
            cached = self.cache.get_stock_data(symbol)
            if cached:
                logger.info(f"📦 Using cached data for {symbol}")
                return cached.get('count', 0)
        
        logger.info(f"🌐 Fetching fresh data for {symbol} from Yahoo API...")
        
        try:
            # Add delay to be respectful
            time.sleep(random.uniform(1, 2))
            
            # Use the chart API which we know works
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
            response = self.session.get(url)
            data = response.json()
            
            # Parse the response
            if 'chart' not in data or 'result' not in data['chart'] or not data['chart']['result']:
                logger.warning(f"No data for {symbol}")
                return 0
            
            result = data['chart']['result'][0]
            
            # Get timestamps and prices
            timestamps = result.get('timestamp', [])
            quote = result.get('indicators', {}).get('quote', [{}])[0]
            closes = quote.get('close', [])
            
            # Prepare prices for database
            prices = []
            for i, ts in enumerate(timestamps):
                if i < len(closes) and closes[i] is not None:
                    date_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                    prices.append((date_str, float(closes[i])))
            
            # Save last 180 days
            prices = prices[-180:]
            
            if prices:
                self.db.save_prices(symbol, prices)
                self.db.cleanup_old_data()
                
                result = {
                    'symbol': symbol, 
                    'count': len(prices), 
                    'timestamp': datetime.now().isoformat()
                }
                self.cache.set_stock_data(symbol, result)
                self.cache.invalidate_stock(symbol)
                
                logger.info(f"✅ Saved {len(prices)} days for {symbol}")
                return len(prices)
            
            return 0
            
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return 0
    
    def fetch_all(self, force_refresh=False):
        results = {}
        for symbol in self.stocks:
            results[symbol] = self.fetch_stock(symbol, force_refresh)
        return results