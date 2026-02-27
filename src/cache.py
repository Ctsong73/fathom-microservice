import redis
import json
from datetime import timedelta
import logging
import os

logger = logging.getLogger(__name__)

class StockCache:
    def __init__(self, host=None, port=None, db=None, ttl=3600):
        """Initialize Redis cache with Time-To-Live (TTL) in seconds"""
        host = host or os.getenv('REDIS_HOST', 'localhost')
        port = int(port or os.getenv('REDIS_PORT', 6379))
        db = int(db or os.getenv('REDIS_DB', 0))
        
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.ttl = ttl  # Cache expires after 1 hour by default
        self._check_connection()
    
    def _check_connection(self):
        """Check if Redis is running"""
        try:
            self.client.ping()
            logger.info("✅ Redis connected successfully")
        except redis.ConnectionError:
            logger.warning("⚠️ Redis not running. Cache disabled.")
            self.client = None
    
    def get_stock_data(self, symbol):
        """Get cached stock data for a symbol"""
        if not self.client:
            return None
        
        key = f"stock:{symbol}"
        data = self.client.get(key)
        
        if data:
            logger.info(f"✅ Cache hit for {symbol}")
            return json.loads(data)
        
        logger.info(f"❌ Cache miss for {symbol}")
        return None
    
    def set_stock_data(self, symbol, data):
        """Cache stock data with TTL"""
        if not self.client:
            return
        
        key = f"stock:{symbol}"
        self.client.setex(key, self.ttl, json.dumps(data))
        logger.info(f"💾 Cached {symbol} for {self.ttl} seconds")
    
    def get_momentum(self, symbol):
        """Get cached momentum calculation"""
        if not self.client:
            return None
        
        key = f"momentum:{symbol}"
        data = self.client.get(key)
        
        if data:
            logger.info(f"✅ Cache hit for {symbol} momentum")
            return json.loads(data)
        
        return None
    
    def set_momentum(self, symbol, data):
        """Cache momentum calculation (shorter TTL)"""
        if not self.client:
            return
        
        key = f"momentum:{symbol}"
        # Momentum cached for 5 minutes since it changes less frequently
        self.client.setex(key, 300, json.dumps(data))
    
    def invalidate_stock(self, symbol):
        """Remove cached data for a stock (when fetching fresh data)"""
        if not self.client:
            return
        
        self.client.delete(f"stock:{symbol}")
        self.client.delete(f"momentum:{symbol}")
        logger.info(f"🗑️ Invalidated cache for {symbol}")
    
    def get_cache_stats(self):
        """Get cache statistics"""
        if not self.client:
            return {"status": "Redis not connected"}
        
        info = self.client.info()
        return {
            "connected_clients": info.get("connected_clients", 0),
            "used_memory_human": info.get("used_memory_human", "0"),
            "total_connections_received": info.get("total_connections_received", 0),
            "uptime_in_seconds": info.get("uptime_in_seconds", 0)
        }
