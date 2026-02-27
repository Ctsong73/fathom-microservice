import pandas as pd
import numpy as np
from database import Database
from cache import StockCache

class MomentumCalculator:
    def __init__(self):
        self.db = Database()
        self.cache = StockCache()
    
    def get_momentum(self, symbol):
        """Calculate 6-month momentum for a stock"""
        # Check cache first
        cached = self.cache.get_momentum(symbol)
        if cached:
            return cached

        prices = self.db.get_prices(symbol, days=180)
        
        if not prices or len(prices) < 20:
            return {
                'symbol': symbol,
                'current_price': 0,
                'price_6mo_ago': 0,
                'momentum_6m': 0,
                'momentum_3m': 0,
                'momentum_1m': 0,
                'volatility': 0,
                'sma_20': 0,
                'sma_50': 0,
                'trend_strength': 0,
                'data_points': len(prices) if prices else 0
            }
        
        # Convert to pandas Series
        dates = [p[0] for p in prices]
        closes = [p[1] for p in prices]
        series = pd.Series(closes, index=pd.to_datetime(dates))
        
        # Calculate momentum
        current = series.iloc[-1]
        six_months_ago = series.iloc[0]
        momentum_6m = ((current / six_months_ago) - 1) * 100
        
        # 3-month momentum
        if len(series) >= 63:
            three_months_ago = series.iloc[-63]
            momentum_3m = ((current / three_months_ago) - 1) * 100
        else:
            momentum_3m = 0
        
        # 1-month momentum
        if len(series) >= 21:
            one_month_ago = series.iloc[-21]
            momentum_1m = ((current / one_month_ago) - 1) * 100
        else:
            momentum_1m = 0
        
        # Calculate volatility
        returns = series.pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) * 100
        
        # Moving averages
        sma_20 = series.rolling(window=20).mean().iloc[-1] if len(series) >= 20 else 0
        sma_50 = series.rolling(window=50).mean().iloc[-1] if len(series) >= 50 else 0
        
        # Trend strength
        up_days = (returns > 0).sum()
        trend_strength = (up_days / len(returns)) * 100 if len(returns) > 0 else 0
        
        return {
            'symbol': symbol,
            'current_price': round(current, 2),
            'price_6mo_ago': round(six_months_ago, 2),
            'momentum_6m': round(momentum_6m, 2),
            'momentum_3m': round(momentum_3m, 2),
            'momentum_1m': round(momentum_1m, 2),
            'volatility': round(volatility, 2),
            'sma_20': round(sma_20, 2),
            'sma_50': round(sma_50, 2),
            'trend_strength': round(trend_strength, 2),
            'data_points': len(prices)
        }
        
        # Cache the result
        self.cache.set_momentum(symbol, result)
        
        return result
