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


def ensure_schema():
    """Create additive tables/indexes for existing volumes (init.sql only runs on first boot)."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS foreign_ref_posts (
            id BIGSERIAL PRIMARY KEY,
            post_id TEXT NOT NULL,
            lang_label TEXT NOT NULL,
            leads INTEGER DEFAULT 0,
            post_link TEXT,
            image_link TEXT,
            post_time TIMESTAMP NULL,
            post_type TEXT,
            caption_original TEXT,
            caption_zh TEXT,
            post_likes BIGINT DEFAULT 0,
            post_comments BIGINT DEFAULT 0,
            post_shares BIGINT DEFAULT 0,
            source_url TEXT NOT NULL DEFAULT '',
            source_sheet TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(source_url, source_sheet, post_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_foreign_ref_lang ON foreign_ref_posts(lang_label)",
        "CREATE INDEX IF NOT EXISTS idx_foreign_ref_type ON foreign_ref_posts(post_type)",
        "CREATE INDEX IF NOT EXISTS idx_foreign_ref_leads ON foreign_ref_posts(leads)",
        "CREATE INDEX IF NOT EXISTS idx_foreign_ref_post_time ON foreign_ref_posts(post_time)",
        "CREATE INDEX IF NOT EXISTS idx_foreign_ref_lang_type ON foreign_ref_posts(lang_label, post_type)",
    ]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for sql in statements:
                cur.execute(sql)
        conn.commit()
