from flask import Flask, render_template, jsonify
from fetcher import StockFetcher
from models import MomentumCalculator
from database import Database
from cache import StockCache

app = Flask(__name__)
fetcher = StockFetcher()
calculator = MomentumCalculator()
db = Database()
cache = StockCache()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/stock/<symbol>')
def stock_detail(symbol):
    if symbol not in ['C', 'XOM', 'NEM']:
        return "Stock not found", 404
    return render_template('stock.html', symbol=symbol)

@app.route('/api/stocks/<symbol>/momentum')
def get_momentum(symbol):
    result = calculator.get_momentum(symbol)
    if not result:
        return jsonify({'error': 'No data available'}), 404
    return jsonify(result)

@app.route('/api/fetch/<symbol>')
def fetch_stock(symbol):
    count = fetcher.fetch_stock(symbol)
    return jsonify({'symbol': symbol, 'records': count})

@app.route('/api/fetch/all')
def fetch_all():
    results = fetcher.fetch_all()
    return jsonify(results)

if __name__ == '__main__':
    print("🌊 Fathom Microservice Starting...")
    print("Stocks: C, XOM, NEM")
    
    # Fetch initial data
    with app.app_context():
        print("Fetching initial data...")
        fetcher.fetch_all()
    
    app.run(host='0.0.0.0', port=5000, debug=True)

# Cache management endpoints
@app.route('/api/cache/stats')
def cache_stats():
    """Get cache statistics"""
    return jsonify(cache.get_cache_stats())

@app.route('/api/cache/clear/<symbol>')
def cache_clear(symbol):
    """Clear cache for a specific stock"""
    cache.invalidate_stock(symbol)
    return jsonify({'message': f'Cache cleared for {symbol}'})

@app.route('/api/cache/clear/all')
def cache_clear_all():
    """Clear all cache"""
    for symbol in ['C', 'XOM', 'NEM']:
        cache.invalidate_stock(symbol)
    return jsonify({'message': 'All cache cleared'})

@app.route('/api/fetch/refresh/<symbol>')
def fetch_refresh(symbol):
    """Force refresh data for a stock (bypass cache)"""
    count = fetcher.fetch_stock(symbol, force_refresh=True)
    return jsonify({'symbol': symbol, 'records': count, 'refreshed': True})

@app.route('/api/fetch/refresh/all')
def fetch_refresh_all():
    """Force refresh all stocks"""
    results = fetcher.fetch_all(force_refresh=True)
    return jsonify({'message': 'All stocks refreshed', 'results': results})
