import os
import re
import time
from datetime import datetime, timedelta
from dateutil import parser
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
from db import pool

CONFIG_SHEET_URL = os.environ.get("CONFIG_SHEET_URL", "")
CONFIG_PAGES_SHEET_NAME = os.environ.get("CONFIG_PAGES_SHEET_NAME", "专页配置")
SUMMARY_CONFIG_SHEET_NAME = os.environ.get("SUMMARY_CONFIG_SHEET_NAME", "帖文汇总")
CHURCH_CONFIG_SHEET_NAME = os.environ.get("CHURCH_CONFIG_SHEET_NAME", "交教会帖文")
INVITE_ONLINE_CONFIG_SHEET_NAME = os.environ.get("INVITE_ONLINE_CONFIG_SHEET_NAME", "邀约上线")
RANK_SHEET_NAME = os.environ.get("RANK_SHEET_NAME", "帖文排行")
RANK_START_ROW = int(os.environ.get("RANK_START_ROW", "3"))
RANK_PAGE_INTERVAL_SECONDS = max(0.0, float(os.environ.get("RANK_PAGE_INTERVAL_SECONDS", "2")))
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/app/secrets/credentials.json")
# Burst 50 reads, then wait 60s. Default quota is 60 reads / minute / user.
GOOGLE_SHEETS_BATCH_SIZE = max(1, int(os.environ.get("GOOGLE_SHEETS_BATCH_SIZE", "50")))
GOOGLE_SHEETS_BATCH_WAIT = max(1, int(os.environ.get("GOOGLE_SHEETS_BATCH_WAIT", "60")))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]
_ss_cache = {}
_batch_count = 0
_quota_cooldown_until = 0.0

# Live progress: stdout (docker logs / exec) + sync_logs.message while running.
_progress = None


def _fmt_dur(seconds):
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(round(seconds)), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


class _SyncProgress:
    def __init__(self, log_id=None):
        self.log_id = log_id
        self.started = time.monotonic()
        self.lines = []
        self.ok_sheets = 0
        self.fail_sheets = 0

    def emit(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        elapsed = _fmt_dur(time.monotonic() - self.started)
        line = f"[{ts} +{elapsed}] {msg}"
        print(line, flush=True)
        self.lines.append(line)
        if self.log_id is not None:
            log_update(self.log_id, "\n".join(self.lines[-60:])[-8000:])


def progress(msg):
    """Print a timestamped progress line; also persist to sync_logs when a run is active."""
    if _progress is not None:
        _progress.emit(msg)
        return
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _progress_summary_text(summary):
    lines = _progress.lines if _progress is not None else []
    body = "\n".join(lines)
    if not summary:
        return body[-8000:]
    room = 8000 - len(summary) - 2
    if room <= 0:
        return summary[:8000]
    if len(body) > room:
        body = "…\n" + body[-(room - 2):]
    return f"{summary}\n\n{body}"


def norm(v):
    return "" if v is None else str(v).strip()

def norm_post_id(v):
    """Normalize post IDs so Sheets numeric / scientific forms still match across tables.

    Google UNFORMATTED_VALUE often returns large IDs as float (precision loss) or
    strings like '1.234567890123456e+16' / '12345.0'. Rank / summary / project
    sheets must land on the same string or joins only return post_id.
    """
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return ""
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if abs(v) >= 1e15 or v == int(v):
            try:
                return str(int(round(v)))
            except Exception:
                return norm(v)
        return norm(v)
    s = norm(v).replace(",", "").replace("，", "")
    if not s:
        return ""
    # scientific notation text
    if re.fullmatch(r"-?\d+(?:\.\d+)?[eE][+-]?\d+", s):
        try:
            return str(int(round(float(s))))
        except Exception:
            return s
    # trailing .0 from numeric cells rendered as text
    if re.fullmatch(r"-?\d+\.0+", s):
        return s.split(".", 1)[0]
    # pure integer string (possibly with spaces already stripped)
    if re.fullmatch(r"-?\d+", s):
        return s
    return s

def to_int(v):
    s = norm(v).replace(",", "").replace("，", "")
    if not s: return 0
    try: return int(float(s))
    except Exception: return 0

def to_percent_int(v):
    """Parse gender/ratio cells into integer percentage points (e.g. 14 for 14%).

    Supports common Google Sheets forms:
    - formatted percent raw value 0.14  → 14
    - text "14%" / "14％"               → 14
    - plain number 14                   → 14
    """
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        f = float(v)
        if 0 < abs(f) < 1:
            return int(round(f * 100))
        return int(round(f))
    s = norm(v).replace(",", "").replace("，", "").strip()
    if not s:
        return 0
    has_pct = "%" in s or "％" in s
    s = s.replace("%", "").replace("％", "").strip()
    try:
        f = float(s)
    except Exception:
        return 0
    if has_pct:
        return int(round(f))
    if 0 < abs(f) < 1:
        return int(round(f * 100))
    return int(round(f))

def sheet_id_from_url(url):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url or "")
    return m.group(1) if m else norm(url)

def parse_google_date(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    s = norm(v)
    if not s: return None
    try: return parser.parse(s).date()
    except Exception: return None

def parse_google_datetime(v):
    if v is None or v == "": return None
    if isinstance(v, (int, float)):
        return datetime(1899, 12, 30) + timedelta(days=float(v))
    s = norm(v)
    if not s: return None
    try: return parser.parse(s)
    except Exception: return None

def col_to_index(col):
    s = norm(col).upper()
    if not s: return None
    if s.isdigit(): return int(s) - 1
    n = 0
    for ch in s:
        if "A" <= ch <= "Z": n = n * 26 + ord(ch) - ord("A") + 1
    return n - 1 if n > 0 else None

def header_map(headers):
    return {norm(h): i for i, h in enumerate(headers)}

def value_by_headers(row, hmap, names):
    for name in names:
        idx = hmap.get(name)
        if idx is not None and idx < len(row): return row[idx]
    return ""

def _header_index(hmap, names):
    """Return 0-based column index for the first matching header name, else None."""
    for name in names:
        if name in hmap:
            return hmap[name]
    return None

def _is_quota_error(exc):
    msg = str(exc)
    if "429" in msg or "Quota" in msg or "quota" in msg or "rateLimitExceeded" in msg:
        return True
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None) if resp is not None else None
    return code == 429


def _retry_after_seconds(exc, fallback):
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw:
            try:
                return max(int(float(raw)), 1)
            except (TypeError, ValueError):
                pass
    return fallback


def _pace_google_api():
    """Read GOOGLE_SHEETS_BATCH_SIZE times, then wait GOOGLE_SHEETS_BATCH_WAIT seconds."""
    global _batch_count
    now = time.monotonic()
    if _quota_cooldown_until > now:
        delay = _quota_cooldown_until - now
        if delay > 0.05:
            progress(f"    配额冷却，等待 {delay:.0f}s…")
            time.sleep(delay)
        _batch_count = 0

    if _batch_count >= GOOGLE_SHEETS_BATCH_SIZE:
        progress(
            f"    已连续读取 {_batch_count} 次，"
            f"等待 {GOOGLE_SHEETS_BATCH_WAIT}s 后再继续…"
        )
        time.sleep(GOOGLE_SHEETS_BATCH_WAIT)
        _batch_count = 0

    _batch_count += 1


def _mark_quota_hit(extra_seconds=60):
    global _quota_cooldown_until, _batch_count
    _quota_cooldown_until = max(_quota_cooldown_until, time.monotonic() + extra_seconds)
    _batch_count = 0


def _reset_google_session():
    global _batch_count, _quota_cooldown_until
    _ss_cache.clear()
    _batch_count = 0
    _quota_cooldown_until = 0.0


def call_retry(fn, *args, **kwargs):
    # Quota window is 1 minute; first wait must refill it, then back off further.
    waits = [60, 60, 90, 120, 180, 180, 180, 180]
    attempts = len(waits)
    for i in range(attempts + 1):
        _pace_google_api()
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            if _is_quota_error(e) and i < attempts:
                cooldown = max(_retry_after_seconds(e, waits[i]), waits[i])
                _mark_quota_hit(cooldown)
                progress(
                    f"    Google API 限流/配额，冷却 {cooldown}s 后重试"
                    f"（第 {i + 1}/{attempts} 次）…"
                )
                continue
            raise


def get_gc():
    creds = Credentials.from_service_account_file(GOOGLE_APPLICATION_CREDENTIALS, scopes=SCOPES)
    return gspread.authorize(creds)


def _quoted_sheet_range(worksheet_name, cell_range=None):
    title = (worksheet_name or "").replace("'", "''")
    rng = f"'{title}'"
    if cell_range:
        rng = f"{rng}!{cell_range}"
    return rng


def open_spreadsheet(gc, sheet_url):
    sid = sheet_id_from_url(sheet_url)
    sh = _ss_cache.get(sid)
    if sh is None:
        sh = gc.open_by_key(sid)
        _ss_cache[sid] = sh
    return sh


def sheet_values(gc, sheet_url, worksheet_name, cell_range=None, value_render_option=None, date_time_render_option=None):
    """One Sheets values.get call (skips extra spreadsheet-metadata roundtrips)."""
    sh = open_spreadsheet(gc, sheet_url)
    rng = _quoted_sheet_range(worksheet_name, cell_range)
    params = {}
    if value_render_option:
        params["valueRenderOption"] = value_render_option
    if date_time_render_option:
        params["dateTimeRenderOption"] = date_time_render_option
    data = call_retry(sh.values_get, rng, params=params or None)
    return data.get("values") or []

def log_start(scope):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_logs(scope,status,message) VALUES(%s,%s,%s) RETURNING id", (scope, "running", ""))
            log_id = cur.fetchone()[0]
        conn.commit()
    return log_id

def log_update(log_id, message):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sync_logs SET message=%s WHERE id=%s", (message[:8000], log_id))
        conn.commit()

def log_finish(log_id, status, message):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sync_logs SET status=%s,message=%s,finished_at=NOW() WHERE id=%s", (status, message[:8000], log_id))
        conn.commit()

def sync_pages(gc):
    label = CONFIG_PAGES_SHEET_NAME
    progress(f"→ 配置表「{label}」读取中…")
    t0 = time.monotonic()
    rows = sheet_values(gc, CONFIG_SHEET_URL, CONFIG_PAGES_SHEET_NAME)
    count = 0
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pages")
            for row in rows[1:]:
                sheet_url = norm(row[0]) if len(row) > 0 else ""
                page_code = norm(row[1]) if len(row) > 1 else ""
                admin_name = norm(row[2]) if len(row) > 2 else ""
                page_id = norm(row[3]) if len(row) > 3 else ""
                enabled_text = norm(row[4]) if len(row) > 4 else ""
                if not sheet_url or not page_code or not admin_name: continue
                enabled = enabled_text not in ["否", "停用", "false", "FALSE", "0", "no", "NO"]
                cur.execute("INSERT INTO admins(name) VALUES(%s) ON CONFLICT(name) DO NOTHING", (admin_name,))
                cur.execute("""
                    INSERT INTO pages(page_code,admin_name,page_id,sheet_url,enabled)
                    VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(page_code,admin_name) DO UPDATE SET
                    page_id=EXCLUDED.page_id, sheet_url=EXCLUDED.sheet_url, enabled=EXCLUDED.enabled
                """, (page_code, admin_name, page_id, sheet_url, enabled))
                count += 1
        conn.commit()
    if _progress is not None:
        _progress.ok_sheets += 1
    progress(f"✓ 配置表「{label}」完成 {count} 个专页，耗时 {_fmt_dur(time.monotonic() - t0)}")
    return count

def sync_summary_source(gc, source_name, source_url, source_sheet):
    rows = sheet_values(
        gc, source_url, source_sheet,
        value_render_option="UNFORMATTED_VALUE",
        date_time_render_option="SERIAL_NUMBER",
    )
    if not rows: return 0
    hmap = header_map(rows[0]); count = 0
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for row in rows[1:]:
                post_id = norm_post_id(value_by_headers(row, hmap, ["帖文ID", "评论ID", "post_id"]))
                if not post_id: continue
                post_time = parse_google_datetime(value_by_headers(row, hmap, ["帖文时间", "发帖日期", "post_time"]))
                cur.execute("""
                    INSERT INTO post_summaries(
                      post_id, post_info, post_info_translation, post_link, post_time,
                      display_media, post_likes, post_comments, post_shares, post_type,
                      post_ocr, post_ocr_translation, video_original, video_translation,
                      author_id, page_id, source, image_link, page_post_type,
                      summary_source_name, summary_source_url, summary_source_sheet, updated_at
                    ) VALUES (
                      %(post_id)s,%(post_info)s,%(post_info_translation)s,%(post_link)s,%(post_time)s,
                      %(display_media)s,%(post_likes)s,%(post_comments)s,%(post_shares)s,%(post_type)s,
                      %(post_ocr)s,%(post_ocr_translation)s,%(video_original)s,%(video_translation)s,
                      %(author_id)s,%(page_id)s,%(source)s,%(image_link)s,%(page_post_type)s,
                      %(summary_source_name)s,%(summary_source_url)s,%(summary_source_sheet)s,NOW()
                    ) ON CONFLICT(post_id) DO UPDATE SET
                      post_info=EXCLUDED.post_info, post_info_translation=EXCLUDED.post_info_translation,
                      post_link=EXCLUDED.post_link, post_time=EXCLUDED.post_time,
                      display_media=EXCLUDED.display_media, post_likes=EXCLUDED.post_likes,
                      post_comments=EXCLUDED.post_comments, post_shares=EXCLUDED.post_shares,
                      post_type=EXCLUDED.post_type, post_ocr=EXCLUDED.post_ocr,
                      post_ocr_translation=EXCLUDED.post_ocr_translation, video_original=EXCLUDED.video_original,
                      video_translation=EXCLUDED.video_translation, author_id=EXCLUDED.author_id,
                      page_id=EXCLUDED.page_id, source=EXCLUDED.source, image_link=EXCLUDED.image_link,
                      page_post_type=EXCLUDED.page_post_type, summary_source_name=EXCLUDED.summary_source_name,
                      summary_source_url=EXCLUDED.summary_source_url, summary_source_sheet=EXCLUDED.summary_source_sheet,
                      updated_at=NOW()
                """, {
                    "post_id": post_id,
                    "post_info": norm(value_by_headers(row, hmap, ["帖文信息"])),
                    "post_info_translation": norm(value_by_headers(row, hmap, ["帖文信息翻译"])),
                    "post_link": norm(value_by_headers(row, hmap, ["帖文链接"])),
                    "post_time": post_time,
                    "display_media": norm(value_by_headers(row, hmap, ["帖文多媒体", "图片链接"])),
                    "post_likes": to_int(value_by_headers(row, hmap, ["👍 帖文点赞", "帖文点赞", "点赞"])),
                    "post_comments": to_int(value_by_headers(row, hmap, ["💬 帖文评论", "帖文评论", "评论"])),
                    "post_shares": to_int(value_by_headers(row, hmap, ["⤴️ 帖文分享", "帖文分享", "分享"])),
                    "post_type": norm(value_by_headers(row, hmap, ["帖文类型"])),
                    "post_ocr": norm(value_by_headers(row, hmap, ["帖文OCR"])),
                    "post_ocr_translation": norm(value_by_headers(row, hmap, ["帖文OCR文本翻译"])),
                    "video_original": norm(value_by_headers(row, hmap, ["视频原文"])),
                    "video_translation": norm(value_by_headers(row, hmap, ["视频内容翻译"])),
                    "author_id": norm(value_by_headers(row, hmap, ["作者ID"])),
                    "page_id": norm(value_by_headers(row, hmap, ["专页ID"])),
                    "source": norm(value_by_headers(row, hmap, ["来源"])),
                    "image_link": norm(value_by_headers(row, hmap, ["图片链接"])),
                    "page_post_type": norm(value_by_headers(row, hmap, ["专页-帖文类型"])),
                    "summary_source_name": source_name,
                    "summary_source_url": source_url,
                    "summary_source_sheet": source_sheet,
                })
                count += 1
        conn.commit()
    return count

def sync_summaries(gc):
    label = SUMMARY_CONFIG_SHEET_NAME
    progress(f"→ 配置表「{label}」读取中…")
    t0 = time.monotonic()
    cfg_rows = sheet_values(gc, CONFIG_SHEET_URL, SUMMARY_CONFIG_SHEET_NAME)
    sources = []
    for row in cfg_rows[1:]:
        source_name = norm(row[0]) if len(row) > 0 else ""
        source_url = norm(row[1]) if len(row) > 1 else ""
        source_sheet = norm(row[2]) if len(row) > 2 else ""
        if not source_url or not source_sheet:
            continue
        sources.append((source_name or source_sheet, source_url, source_sheet))
    if _progress is not None:
        _progress.ok_sheets += 1
    progress(f"✓ 配置表「{label}」共 {len(sources)} 个来源表，耗时 {_fmt_dur(time.monotonic() - t0)}")
    total = 0
    errors = []
    for i, (source_name, source_url, source_sheet) in enumerate(sources, 1):
        progress(f"→ [{i}/{len(sources)}] 帖文汇总「{source_name}」读取中…")
        t1 = time.monotonic()
        try:
            n = sync_summary_source(gc, source_name, source_url, source_sheet)
            total += n
            if _progress is not None:
                _progress.ok_sheets += 1
            progress(
                f"✓ [{i}/{len(sources)}] 帖文汇总「{source_name}」完成 {n} 行，"
                f"耗时 {_fmt_dur(time.monotonic() - t1)}"
            )
        except Exception as e:
            errors.append(f"{source_name or source_url}: {e}")
            if _progress is not None:
                _progress.fail_sheets += 1
            progress(f"✗ [{i}/{len(sources)}] 帖文汇总「{source_name}」失败：{e}")
    return total, errors

def sync_rank_for_page(gc, page):
    # 新版“帖文排行”列结构：
    # A 帖文ID | B 帖文链接 | C 引流日期 | D 引流
    # E-G 预留/忽略 | H 男(比例%) | I 女(比例%) | J 邀约 | K 上线 | L 交教会
    # 男/女在表格中为百分比（如 14%、0.14），入库为整数百分点（14）。
    # 答题 answers 和得人 gained 不从表格读取，固定存为 0。
    rows = sheet_values(
        gc, page["sheet_url"], RANK_SHEET_NAME,
        cell_range=f"A{RANK_START_ROW}:L",
        value_render_option="UNFORMATTED_VALUE",
        date_time_render_option="SERIAL_NUMBER",
    )
    count = 0
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for row in rows:
                post_id = norm_post_id(row[0]) if len(row) > 0 else ""
                if not post_id: continue

                post_link = norm(row[1]) if len(row) > 1 else ""
                lead_date = parse_google_date(row[2] if len(row) > 2 else "")
                leads = to_int(row[3] if len(row) > 3 else "")
                male = to_percent_int(row[7] if len(row) > 7 else "")
                female = to_percent_int(row[8] if len(row) > 8 else "")
                answers = 0
                invites = to_int(row[9] if len(row) > 9 else "")
                online = to_int(row[10] if len(row) > 10 else "")
                church = to_int(row[11] if len(row) > 11 else "")
                gained = 0

                cur.execute("""
                    INSERT INTO post_rank_stats(page_code,admin_name,post_id,post_link,lead_date,male,female,leads,answers,invites,online,church,gained,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT(page_code,admin_name,post_id,lead_date) DO UPDATE SET
                    post_link=EXCLUDED.post_link, male=EXCLUDED.male, female=EXCLUDED.female, leads=EXCLUDED.leads,
                    answers=EXCLUDED.answers, invites=EXCLUDED.invites, online=EXCLUDED.online,
                    church=EXCLUDED.church, gained=EXCLUDED.gained, updated_at=NOW()
                """, (
                    page["page_code"], page["admin_name"], post_id,
                    post_link, lead_date,
                    male, female, leads, answers,
                    invites, online, church, gained,
                ))
                count += 1
        conn.commit()
    return count

def ensure_project_items_columns():
    """Ensure project_items has columns needed by church / invite_online sync."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE project_items ADD COLUMN IF NOT EXISTS lead_id TEXT")
            cur.execute("ALTER TABLE project_items ADD COLUMN IF NOT EXISTS friend_channel TEXT")
        conn.commit()

def sync_project_from_config(gc, config_sheet_name, project_name, has_online=False):
    kind = "邀约上线" if has_online else "交教会"
    progress(f"→ 配置表「{config_sheet_name}」读取中…")
    t0 = time.monotonic()
    try:
        cfg_rows = sheet_values(gc, CONFIG_SHEET_URL, config_sheet_name)
    except Exception as e:
        if _progress is not None:
            _progress.fail_sheets += 1
        progress(f"✗ 配置表「{config_sheet_name}」打开失败：{e}")
        return 0, []
    parsed = []
    for cfg in cfg_rows[1:]:
        source_url = norm(cfg[0]) if len(cfg) > 0 else ""
        source_sheet = norm(cfg[1]) if len(cfg) > 1 else ""
        post_col = col_to_index(cfg[2]) if len(cfg) > 2 else None
        date_col = col_to_index(cfg[3]) if len(cfg) > 3 else None
        # 邀约上线配置：A URL | B sheet | C 帖文列 | D 日期列 | E 状态列 | F 上线码 | G 线索ID列 | H 加友渠道列
        # 交教会配置：  A URL | B sheet | C 帖文列 | D 日期列 | E 线索ID列 | F 加友渠道列
        if has_online:
            status_col = col_to_index(cfg[4]) if len(cfg) > 4 else None
            online_code = norm(cfg[5]) if len(cfg) > 5 else ""
            lead_col = col_to_index(cfg[6]) if len(cfg) > 6 else None
            channel_col = col_to_index(cfg[7]) if len(cfg) > 7 else None
        else:
            status_col = None
            online_code = ""
            lead_col = col_to_index(cfg[4]) if len(cfg) > 4 else None
            channel_col = col_to_index(cfg[5]) if len(cfg) > 5 else None
        if not source_url or not source_sheet or post_col is None or date_col is None:
            continue
        parsed.append({
            "source_url": source_url,
            "source_sheet": source_sheet,
            "post_col": post_col,
            "date_col": date_col,
            "status_col": status_col,
            "online_code": online_code,
            "lead_col": lead_col,
            "channel_col": channel_col,
        })
    if _progress is not None:
        _progress.ok_sheets += 1
    progress(
        f"✓ 配置表「{config_sheet_name}」共 {len(parsed)} 个来源表，"
        f"耗时 {_fmt_dur(time.monotonic() - t0)}"
    )
    count = 0
    errors = []
    ensure_project_items_columns()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_items WHERE project_name=%s", (project_name,))
        conn.commit()
    for i, item in enumerate(parsed, 1):
        source_url = item["source_url"]
        source_sheet = item["source_sheet"]
        post_col = item["post_col"]
        date_col = item["date_col"]
        status_col = item["status_col"]
        online_code = item["online_code"]
        lead_col = item["lead_col"]
        channel_col = item["channel_col"]
        progress(f"→ [{i}/{len(parsed)}] {kind}「{source_sheet}」读取中…")
        t1 = time.monotonic()
        try:
            rows = sheet_values(
                gc, source_url, source_sheet,
                value_render_option="UNFORMATTED_VALUE",
                date_time_render_option="SERIAL_NUMBER",
            )
        except Exception as e:
            errors.append(f"{source_sheet}: {e}")
            if _progress is not None:
                _progress.fail_sheets += 1
            progress(f"✗ [{i}/{len(parsed)}] {kind}「{source_sheet}」失败：{e}")
            continue
        if not rows:
            if _progress is not None:
                _progress.ok_sheets += 1
            progress(f"· [{i}/{len(parsed)}] {kind}「{source_sheet}」空表，跳过")
            continue
        hmap = header_map(rows[0])
        # 未在配置里写列号时，再按表头名回退（表头必须完全一致，含空格会匹配失败）
        if lead_col is None:
            lead_col = _header_index(hmap, ["线索ID", "线索id", "线索Id", "lead_id", "Lead ID", "线索编号", "线索id号"])
        if channel_col is None:
            channel_col = _header_index(hmap, ["加友渠道", "加好友渠道", "加友渠道名", "friend_channel", "加粉渠道", "渠道"])
        sheet_count = 0
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for idx, row in enumerate(rows[1:], start=2):
                    post_id = norm_post_id(row[post_col]) if post_col < len(row) else ""
                    project_date = parse_google_date(row[date_col]) if date_col < len(row) else None
                    if not post_id: continue

                    status_text = norm(row[status_col]) if has_online and status_col is not None and status_col < len(row) else ""
                    is_online = bool(has_online and online_code and online_code in status_text)
                    lead_id = norm(row[lead_col]) if lead_col is not None and lead_col < len(row) else ""
                    friend_channel = norm(row[channel_col]) if channel_col is not None and channel_col < len(row) else ""
                    cur.execute("""
                        INSERT INTO project_items(
                          project_name,post_id,project_date,is_online,online_status_text,online_code,
                          lead_id,friend_channel,source_sheet_url,source_sheet_name,source_row,synced_at
                        )
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT(project_name,post_id,project_date,source_sheet_url,source_sheet_name,source_row)
                        DO UPDATE SET is_online=EXCLUDED.is_online, online_status_text=EXCLUDED.online_status_text,
                        online_code=EXCLUDED.online_code, lead_id=EXCLUDED.lead_id,
                        friend_channel=EXCLUDED.friend_channel, synced_at=NOW()
                    """, (
                        project_name, post_id, project_date, is_online, status_text, online_code,
                        lead_id, friend_channel, source_url, source_sheet, idx,
                    ))
                    sheet_count += 1
                    count += 1
            conn.commit()
        if _progress is not None:
            _progress.ok_sheets += 1
        progress(
            f"✓ [{i}/{len(parsed)}] {kind}「{source_sheet}」完成 {sheet_count} 行，"
            f"耗时 {_fmt_dur(time.monotonic() - t1)}"
        )
    return count, errors

def refresh_unmatched():
    progress("→ 刷新未匹配帖文…")
    t0 = time.monotonic()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM unmatched_posts")
            cur.execute("""
                INSERT INTO unmatched_posts(post_id,page_code,admin_name,reason)
                SELECT DISTINCT r.post_id,r.page_code,r.admin_name,'帖文汇总未匹配到'
                FROM post_rank_stats r LEFT JOIN post_summaries s ON s.post_id=r.post_id
                WHERE s.post_id IS NULL
            """)
            unmatched_count = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        conn.commit()
    progress(f"✓ 未匹配帖文 {unmatched_count} 条，耗时 {_fmt_dur(time.monotonic() - t0)}")

def _with_sync_lock(scope, fn):
    """Run fn(gc) under advisory lock; write sync_logs for scope."""
    global _progress
    with pool.connection() as lock_conn:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(860601)")
            got_lock = cur.fetchone()[0]
        lock_conn.commit()
        if not got_lock:
            return {"ok": False, "message": "已有同步正在运行，请稍后再试。"}
        log_id = log_start(scope)
        prev_progress = _progress
        _progress = _SyncProgress(log_id)
        try:
            progress(f"开始同步（scope={scope}）")
            progress(
                f"Google Sheets 限速：连续读取 {GOOGLE_SHEETS_BATCH_SIZE} 次后，"
                f"等待 {GOOGLE_SHEETS_BATCH_WAIT}s"
            )
            progress("正在连接 Google Sheets…")
            _reset_google_session()
            gc = get_gc()
            progress("Google 凭证已就绪")
            msg, errors = fn(gc)
            if errors:
                msg = msg + " 错误：" + " | ".join(errors[:20])
                progress(f"同步结束（部分失败）：{msg}")
                log_finish(log_id, "partial", _progress_summary_text(msg))
            else:
                progress(f"同步结束：{msg}")
                log_finish(log_id, "success", _progress_summary_text(msg))
            return {"ok": True, "message": msg}
        except Exception as e:
            progress(f"同步失败：{e}")
            log_finish(log_id, "failed", _progress_summary_text(str(e)))
            raise
        finally:
            _progress = prev_progress
            with lock_conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(860601)")
            lock_conn.commit()

def run_sync_projects():
    """Only sync 交教会帖文 + 邀约上线 (project_items)."""
    def _run(gc):
        progress("======== 项目同步开始 ========")
        progress("阶段 1/2 交教会帖文")
        church_count, church_errors = sync_project_from_config(gc, CHURCH_CONFIG_SHEET_NAME, "church", False)
        progress("阶段 2/2 邀约上线")
        invite_online_count, invite_online_errors = sync_project_from_config(
            gc, INVITE_ONLINE_CONFIG_SHEET_NAME, "invite_online", True
        )
        errors = church_errors + invite_online_errors
        ok = _progress.ok_sheets if _progress is not None else 0
        fail = _progress.fail_sheets if _progress is not None else len(errors)
        msg = (
            f"交教会 {church_count} 行；邀约上线 {invite_online_count} 行。"
            f"表格成功 {ok} / 失败 {fail}。"
        )
        progress("======== 项目同步完成 ========")
        return msg, errors
    return _with_sync_lock("projects", _run)

def run_sync_all():
    def _run(gc):
        progress("======== 全量同步开始 ========")
        progress("阶段 1/6 专页配置")
        sync_pages(gc)
        progress("阶段 2/6 帖文汇总")
        summary_count, summary_errors = sync_summaries(gc)
        progress("阶段 3/6 交教会帖文")
        church_count, church_errors = sync_project_from_config(gc, CHURCH_CONFIG_SHEET_NAME, "church", False)
        progress("阶段 4/6 邀约上线")
        invite_online_count, invite_online_errors = sync_project_from_config(
            gc, INVITE_ONLINE_CONFIG_SHEET_NAME, "invite_online", True
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT page_code,admin_name,sheet_url FROM pages WHERE enabled=true")
                cols = [d.name for d in cur.description]
                pages = [dict(zip(cols, row)) for row in cur.fetchall()]
        progress(
            f"阶段 5/6 各专页「{RANK_SHEET_NAME}」，共 {len(pages)} 个启用专页"
            + (f"，每个间隔 {RANK_PAGE_INTERVAL_SECONDS:g}s" if RANK_PAGE_INTERVAL_SECONDS > 0 else "")
        )
        rank_total = 0
        rank_errors = []
        for i, page in enumerate(pages, 1):
            name = f"{page.get('page_code') or ''} / {page.get('admin_name') or ''}".strip(" /")
            progress(f"→ [{i}/{len(pages)}] 帖文排行「{name}」读取中…")
            t0 = time.monotonic()
            try:
                n = sync_rank_for_page(gc, page)
                rank_total += n
                if _progress is not None:
                    _progress.ok_sheets += 1
                progress(
                    f"✓ [{i}/{len(pages)}] 帖文排行「{name}」完成 {n} 行，"
                    f"耗时 {_fmt_dur(time.monotonic() - t0)}"
                )
            except Exception as e:
                rank_errors.append(f"{page.get('page_code')}: {e}")
                if _progress is not None:
                    _progress.fail_sheets += 1
                progress(f"✗ [{i}/{len(pages)}] 帖文排行「{name}」失败：{e}")
            if i < len(pages) and RANK_PAGE_INTERVAL_SECONDS > 0:
                time.sleep(RANK_PAGE_INTERVAL_SECONDS)
        progress("阶段 6/6 刷新未匹配帖文")
        refresh_unmatched()
        errors = summary_errors + church_errors + invite_online_errors + rank_errors
        ok = _progress.ok_sheets if _progress is not None else 0
        fail = _progress.fail_sheets if _progress is not None else len(errors)
        msg = (
            f"专页 {len(pages)} 个；汇总 {summary_count} 行；排行 {rank_total} 行；"
            f"交教会 {church_count} 行；邀约上线 {invite_online_count} 行。"
            f"表格成功 {ok} / 失败 {fail}。"
        )
        progress("======== 全量同步完成 ========")
        return msg, errors
    return _with_sync_lock("all", _run)

def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Google Sheets → DB 同步")
    parser.add_argument(
        "scope",
        nargs="?",
        default="all",
        choices=["all", "projects"],
        help="all=全量同步；projects=仅交教会帖文+邀约上线",
    )
    args = parser.parse_args()
    if args.scope == "projects":
        result = run_sync_projects()
    else:
        result = run_sync_all()
    print(json.dumps(result, ensure_ascii=False))
    if not result.get("ok"):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
