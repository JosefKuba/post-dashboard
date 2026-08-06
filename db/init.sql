CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    id SERIAL PRIMARY KEY,
    page_code TEXT NOT NULL,
    admin_name TEXT NOT NULL,
    page_id TEXT,
    sheet_url TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(page_code, admin_name)
);

CREATE TABLE IF NOT EXISTS post_summaries (
    post_id TEXT PRIMARY KEY,
    post_info TEXT,
    post_info_translation TEXT,
    post_link TEXT,
    post_time TIMESTAMP NULL,
    display_media TEXT,
    post_likes BIGINT DEFAULT 0,
    post_comments BIGINT DEFAULT 0,
    post_shares BIGINT DEFAULT 0,
    post_type TEXT,
    post_ocr TEXT,
    post_ocr_translation TEXT,
    video_original TEXT,
    video_translation TEXT,
    author_id TEXT,
    page_id TEXT,
    source TEXT,
    image_link TEXT,
    page_post_type TEXT,
    summary_source_name TEXT,
    summary_source_url TEXT,
    summary_source_sheet TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_rank_stats (
    id BIGSERIAL PRIMARY KEY,
    page_code TEXT NOT NULL,
    admin_name TEXT NOT NULL,
    post_id TEXT NOT NULL,
    post_link TEXT,
    lead_date DATE NULL,
    male INTEGER DEFAULT 0,
    female INTEGER DEFAULT 0,
    leads INTEGER DEFAULT 0,
    answers INTEGER DEFAULT 0,
    invites INTEGER DEFAULT 0,
    online INTEGER DEFAULT 0,
    church INTEGER DEFAULT 0,
    gained INTEGER DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(page_code, admin_name, post_id, lead_date)
);

CREATE TABLE IF NOT EXISTS project_items (
    id BIGSERIAL PRIMARY KEY,
    project_name TEXT NOT NULL,
    post_id TEXT NOT NULL,
    project_date DATE NULL,
    is_online BOOLEAN NOT NULL DEFAULT FALSE,
    online_status_text TEXT,
    online_code TEXT,
    lead_id TEXT,
    friend_channel TEXT,
    source_sheet_url TEXT,
    source_sheet_name TEXT,
    source_row INTEGER,
    synced_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(project_name, post_id, project_date, source_sheet_url, source_sheet_name, source_row)
);

-- 兼容已有库：补齐交教会/邀约上线新增字段
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS lead_id TEXT;
ALTER TABLE project_items ADD COLUMN IF NOT EXISTS friend_channel TEXT;

CREATE TABLE IF NOT EXISTS sync_logs (
    id BIGSERIAL PRIMARY KEY,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS unmatched_posts (
    id BIGSERIAL PRIMARY KEY,
    post_id TEXT NOT NULL,
    page_code TEXT,
    admin_name TEXT,
    reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pages_code_admin ON pages(page_code, admin_name);
CREATE INDEX IF NOT EXISTS idx_pages_page_id ON pages(page_id);
CREATE INDEX IF NOT EXISTS idx_rank_admin ON post_rank_stats(admin_name);
CREATE INDEX IF NOT EXISTS idx_rank_page ON post_rank_stats(page_code);
CREATE INDEX IF NOT EXISTS idx_rank_post ON post_rank_stats(post_id);
CREATE INDEX IF NOT EXISTS idx_rank_lead_date ON post_rank_stats(lead_date);
CREATE INDEX IF NOT EXISTS idx_summary_post_time ON post_summaries(post_time);
CREATE INDEX IF NOT EXISTS idx_project_name_date ON project_items(project_name, project_date);
CREATE INDEX IF NOT EXISTS idx_project_post ON project_items(post_id);
