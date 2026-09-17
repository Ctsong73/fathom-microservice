import csv
import logging
import os
import threading
from collections import defaultdict

from flask import Flask, render_template, jsonify

from fetcher import StockFetcher, STALE_HOURS
from models import MomentumCalculator
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UNIVERSE_CSV = os.environ.get('UNIVERSE_CSV', 'data/mining_stocks.csv')

app = Flask(__name__)


def load_universe():
    """Read the mining universe CSV -> list of (symbol, name, exchange, country, sector)."""
    if not os.path.exists(UNIVERSE_CSV):
        logger.warning(f"Universe file not found: {UNIVERSE_CSV}")
        return []
    with open(UNIVERSE_CSV, newline='') as f:
        return [
            (r['symbol'], r['name'], r['exchange'], r['country'], r['sector'])
            for r in csv.DictReader(f)
        ]


universe = load_universe()
db = Database()
fetcher = StockFetcher(db, [row[0] for row in universe])
calculator = MomentumCalculator(db)


def boot_sync():
    """Background sync of stale stocks so the web server starts responding instantly."""
    logger.info(f"Background sync starting for {len(universe)} stocks...")
    try:
        results = fetcher.fetch_all()
        fresh = sum(1 for v in results.values() if v)
        logger.info(f"Background sync done: {fresh}/{len(universe)} stocks with data")
    except Exception as e:
        logger.error(f"Background sync failed: {e}")


@app.route('/')
def home():
    return render_template('index.html', stocks=db.get_stocks())


@app.route('/stock/<symbol>')
def stock_detail(symbol):
    stock = db.get_stock(symbol)
    if not stock:
        return "Stock not found", 404
    return render_template('stock.html', symbol=stock['symbol'],
                           name=stock['name'], sector=stock['sector'],
                           country=stock['country'], exchange=stock['exchange'])


@app.route('/api/stocks/<symbol>/momentum')
def get_momentum(symbol):
    """Momentum analysis for a single stock, refreshing stale data first."""
    stock = db.get_stock(symbol)
    if not stock:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 404
    try:
        if db.is_stale(symbol, STALE_HOURS):
            logger.info(f"Refreshing stale data for {symbol}")
            fetcher.fetch_stock(symbol, force_refresh=True)

        result = calculator.get_momentum(symbol)

        if result['current_price'] == 0:
            fetcher.fetch_stock(symbol, force_refresh=True)
            result = calculator.get_momentum(symbol)

        result.update({
            'name': stock['name'],
            'sector': stock['sector'],
            'country': stock['country'],
            'exchange': stock['exchange'],
        })
        result['valuation'] = fetcher.get_valuation(symbol)
        return jsonify(result)
    except Exception as e:
        logger.exception(f"Error calculating momentum for {symbol}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/fetch/<symbol>')
def fetch_stock(symbol):
    """Fetch and store data for a single symbol."""
    if not db.get_stock(symbol):
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 404
    count = fetcher.fetch_stock(symbol, force_refresh=True)
    return jsonify({'symbol': symbol, 'records': count})


@app.route('/api/fetch/all')
def fetch_all():
    """Refresh every stock in the universe (blocking; can take a while)."""
    results = fetcher.fetch_all(force_refresh=True)
    return jsonify({'results': results})


@app.route('/health')
def health():
    stocks = db.get_stocks()
    return jsonify({
        'status': 'healthy',
        'universe_size': len(universe),
        'stocks_with_data': sum(1 for s in stocks
                                if db.count_prices(s['symbol']) > 0),
    })


@app.route('/debug/valuation/<symbol>')
def debug_valuation(symbol):
    """Diagnose what Yahoo returns for valuation of one symbol (debug only)."""
    return jsonify(fetcher.debug_valuation(symbol))


@app.route('/debug/db/<symbol>')
def debug_db(symbol):
    """View raw price data in DB for debugging."""
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
    """List all registered routes."""
    import urllib
    routes = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            routes.append({
                'endpoint': rule.endpoint,
                'url': urllib.parse.unquote(rule.rule),
                'methods': list(rule.methods)
            })
    return jsonify(routes)


@app.route('/debug/universe')
def debug_universe():
    """List the tracked mining universe, grouped by sector."""
    grouped = defaultdict(list)
    for s in db.get_stocks():
        grouped[s['sector']].append({
            'symbol': s['symbol'],
            'name': s['name'],
            'country': s['country'],
            'exchange': s['exchange'],
        })
    return jsonify(dict(grouped))


if __name__ == '__main__':
    print(f"fathom Microservice starting - {len(universe)} mining stocks")

    db.sync_universe(universe)

    # Start background data sync without blocking the web server
    threading.Thread(target=boot_sync, daemon=True).start()

    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)