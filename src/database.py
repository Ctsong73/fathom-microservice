import sqlite3
from datetime import datetime, timedelta
import os

class Database:
    def __init__(self, db_path=None):
        # Use environment variable if provided (for Docker), otherwise default
        self.db_path = db_path or os.environ.get('DATABASE_PATH', 'data/stocks.db')
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()
    
    # Rest of your code remains exactly the same...
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stocks (
                symbol TEXT PRIMARY KEY,
                name TEXT
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
        
        stocks = [
            ('C', 'Citigroup Inc.'),
            ('XOM', 'Exxon Mobil Corporation'),
            ('NEM', 'Newmont Corporation')
        ]
        cursor.executemany('INSERT OR IGNORE INTO stocks VALUES (?, ?)', stocks)
        
        conn.commit()
        conn.close()
        print("Database ready with C, XOM, NEM")
    
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
        cursor = conn.cursor()
        cursor.execute('''
            SELECT date, close FROM daily_prices
            WHERE symbol = ? AND date >= ?
            ORDER BY date
        ''', (symbol, cutoff.isoformat()))
        
        rows = cursor.fetchall()
        conn.close()
        return rows
    
    def cleanup_old_data(self):
        cutoff = (datetime.now() - timedelta(days=180)).date()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM daily_prices WHERE date < ?', (cutoff.isoformat(),))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"Cleaned up {deleted} old records")