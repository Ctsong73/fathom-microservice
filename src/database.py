import sqlite3
from datetime import datetime, timedelta
import os


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get('DATABASE_PATH', 'data/stocks.db')
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=10000')
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        # Migrate an older stocks table (symbol, name only) if present.
        cols = [r[1] for r in cursor.execute('PRAGMA table_info(stocks)').fetchall()]
        if cols and 'sector' not in cols:
            cursor.execute('DROP TABLE stocks')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stocks (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                exchange TEXT,
                country TEXT,
                sector TEXT,
                last_fetched TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_prices (
                symbol TEXT,
                date TEXT,
                close REAL,
                PRIMARY KEY (symbol, date)
            )
        ''')

        conn.commit()
        conn.close()

    def sync_universe(self, rows):
        """Upsert the mining universe. rows: (symbol, name, exchange, country, sector)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.executemany('''
            INSERT OR IGNORE INTO stocks (symbol, name, exchange, country, sector)
            VALUES (?, ?, ?, ?, ?)
        ''', rows)
        conn.commit()
        conn.close()

    def get_stocks(self):
        conn = self.get_connection()
        rows = conn.execute(
            'SELECT * FROM stocks ORDER BY sector, name').fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_stock(self, symbol):
        conn = self.get_connection()
        row = conn.execute(
            'SELECT * FROM stocks WHERE symbol = ?', (symbol,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_last_fetched(self, symbol):
        conn = self.get_connection()
        conn.execute(
            'UPDATE stocks SET last_fetched = ? WHERE symbol = ?',
            (datetime.now().isoformat(timespec='seconds'), symbol))
        conn.commit()
        conn.close()

    def is_stale(self, symbol, max_age_hours):
        conn = self.get_connection()
        row = conn.execute(
            'SELECT last_fetched FROM stocks WHERE symbol = ?',
            (symbol,)).fetchone()
        conn.close()
        if row is None or row['last_fetched'] is None:
            return True
        try:
            last = datetime.fromisoformat(row['last_fetched'])
        except ValueError:
            return True
        return (datetime.now() - last) > timedelta(hours=max_age_hours)

    def save_prices(self, symbol, prices):
        conn = self.get_connection()
        cursor = conn.cursor()
        for date_str, close_price in prices:
            cursor.execute('''
                INSERT OR REPLACE INTO daily_prices (symbol, date, close)
                VALUES (?, ?, ?)
            ''', (symbol, date_str, close_price))
        conn.commit()
        conn.close()

    def get_prices(self, symbol, days=180):
        cutoff = (datetime.now() - timedelta(days=days)).date()
        conn = self.get_connection()
        rows = conn.execute('''
            SELECT date, close FROM daily_prices
            WHERE symbol = ? AND date >= ?
            ORDER BY date
        ''', (symbol, cutoff.isoformat())).fetchall()
        conn.close()
        return [(r['date'], r['close']) for r in rows]

    def count_prices(self, symbol):
        conn = self.get_connection()
        n = conn.execute(
            'SELECT COUNT(*) AS n FROM daily_prices WHERE symbol = ?',
            (symbol,)).fetchone()['n']
        conn.close()
        return n

    def cleanup_old_data(self):
        cutoff = (datetime.now() - timedelta(days=180)).date()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM daily_prices WHERE date < ?',
                       (cutoff.isoformat(),))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"Cleaned up {deleted} old records")