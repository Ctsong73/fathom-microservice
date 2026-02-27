from flask import Flask, render_template, jsonify
from fetcher import StockFetcher
from models import MomentumCalculator
from database import Database
from cache import StockCache
import os

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
    """Get momentum data for a specific stock"""
    try:
        # Get the momentum data from calculator
        result = calculator.get_momentum(symbol)
        
        if not result or result.get('current_price') == 0:
            # Fetch additional data if needed
            from fetcher import StockFetcher
            fetcher = StockFetcher()
            count = fetcher.fetch_stock(symbol)
            
            # If we fetched new data, recalculate momentum
            if count > 0:
                result = calculator.get_momentum(symbol)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fetch/<symbol>')
def fetch_stock(symbol):
    """Fetch and store stock data"""
    count = fetcher.fetch_stock(symbol)
    return jsonify({'symbol': symbol, 'records': count})

@app.route('/api/fetch/all')
def fetch_all():
    """Fetch and store all stocks data"""
    results = fetcher.fetch_all()
    return jsonify(results)

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

# Health check endpoint (useful for Render)
@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'stocks': ['C', 'XOM', 'NEM']})

# Debug endpoint to check routes
@app.route('/debug/db/<symbol>')
def debug_db(symbol):
    """View raw price data in DB for debugging"""
    try:
        prices = db.get_prices(symbol, days=365)
        return jsonify({
            'symbol': symbol,
            'count': len(prices),
            'first_5': prices[:5],
            'last_5': prices[-5:]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/routes')
def debug_routes():
    """List all registered routes (helpful for debugging)"""
    import urllib
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'url': urllib.parse.unquote(rule.rule),
            'methods': list(rule.methods)
        })
    return jsonify(routes)

if __name__ == '__main__':
    print("🌊 Fathom Microservice Starting...")
    print("Stocks: C, XOM, NEM")
    
    # Fetch initial data
    with app.app_context():
        print("Fetching initial data...")
        try:
            fetcher.fetch_all()
            print("✅ Initial data fetched successfully")
        except Exception as e:
            print(f"⚠️ Error fetching initial data: {e}")
    
    # Get port from environment variable (for Render)
    port = int(os.environ.get('PORT', 5000))
    
    # In production, debug should be False
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)