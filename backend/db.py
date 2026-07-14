import os
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ["DATABASE_URL"]
pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True)

def fetch_all(sql, params=None):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_one(sql, params=None):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None

def execute(sql, params=None):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
        conn.commit()
