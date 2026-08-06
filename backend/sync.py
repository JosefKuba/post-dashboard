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
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/app/secrets/credentials.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]

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

def call_retry(fn, *args, **kwargs):
    waits = [3, 8, 20, 45]
    for i, wait in enumerate([0] + waits):
        if wait: time.sleep(wait)
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            msg = str(e)
            if "429" in msg or "Quota" in msg or "quota" in msg:
                if i < len(waits):
                    continue
            raise

def get_gc():
    creds = Credentials.from_service_account_file(GOOGLE_APPLICATION_CREDENTIALS, scopes=SCOPES)
    return gspread.authorize(creds)

def open_ws(gc, sheet_url, worksheet_name):
    sh = call_retry(gc.open_by_key, sheet_id_from_url(sheet_url))
    return call_retry(sh.worksheet, worksheet_name)

def get_values(ws, *args, **kwargs):
    return call_retry(ws.get, *args, **kwargs)

def get_all_values(ws, *args, **kwargs):
    return call_retry(ws.get_all_values, *args, **kwargs)

def log_start(scope):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_logs(scope,status,message) VALUES(%s,%s,%s) RETURNING id", (scope, "running", ""))
            log_id = cur.fetchone()[0]
        conn.commit()
    return log_id

def log_finish(log_id, status, message):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE sync_logs SET status=%s,message=%s,finished_at=NOW() WHERE id=%s", (status, message[:3000], log_id))
        conn.commit()

def sync_pages(gc):
    ws = open_ws(gc, CONFIG_SHEET_URL, CONFIG_PAGES_SHEET_NAME)
    rows = get_all_values(ws)
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
        conn.commit()

def sync_summary_source(gc, source_name, source_url, source_sheet):
    ws = open_ws(gc, source_url, source_sheet)
    rows = get_all_values(ws, value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
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
    ws = open_ws(gc, CONFIG_SHEET_URL, SUMMARY_CONFIG_SHEET_NAME)
    cfg_rows = get_all_values(ws)
    total = 0; errors = []
    for row in cfg_rows[1:]:
        source_name = norm(row[0]) if len(row) > 0 else ""
        source_url = norm(row[1]) if len(row) > 1 else ""
        source_sheet = norm(row[2]) if len(row) > 2 else ""
        if not source_url or not source_sheet: continue
        try:
            total += sync_summary_source(gc, source_name or source_sheet, source_url, source_sheet)
        except Exception as e:
            errors.append(f"{source_name or source_url}: {e}")
    return total, errors

def sync_rank_for_page(gc, page):
    ws = open_ws(gc, page["sheet_url"], RANK_SHEET_NAME)
    # 新版“帖文排行”列结构：
    # A 帖文ID | B 帖文链接 | C 引流日期 | D 引流
    # E-G 预留/忽略 | H 男(比例%) | I 女(比例%) | J 邀约 | K 上线 | L 交教会
    # 男/女在表格中为百分比（如 14%、0.14），入库为整数百分点（14）。
    # 答题 answers 和得人 gained 不从表格读取，固定存为 0。
    rows = get_values(ws, f"A{RANK_START_ROW}:L", value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
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
    try:
        ws = open_ws(gc, CONFIG_SHEET_URL, config_sheet_name)
    except Exception:
        return 0, []
    cfg_rows = get_all_values(ws)
    count = 0; errors = []
    ensure_project_items_columns()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM project_items WHERE project_name=%s", (project_name,))
        conn.commit()
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
        if not source_url or not source_sheet or post_col is None or date_col is None: continue
        try:
            source_ws = open_ws(gc, source_url, source_sheet)
            rows = get_all_values(source_ws, value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
        except Exception as e:
            errors.append(f"{source_sheet}: {e}"); continue
        if not rows:
            continue
        hmap = header_map(rows[0])
        # 未在配置里写列号时，再按表头名回退（表头必须完全一致，含空格会匹配失败）
        if lead_col is None:
            lead_col = _header_index(hmap, ["线索ID", "线索id", "线索Id", "lead_id", "Lead ID", "线索编号", "线索id号"])
        if channel_col is None:
            channel_col = _header_index(hmap, ["加友渠道", "加好友渠道", "加友渠道名", "friend_channel", "加粉渠道", "渠道"])
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
                    count += 1
            conn.commit()
    return count, errors

def refresh_unmatched():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM unmatched_posts")
            cur.execute("""
                INSERT INTO unmatched_posts(post_id,page_code,admin_name,reason)
                SELECT DISTINCT r.post_id,r.page_code,r.admin_name,'帖文汇总未匹配到'
                FROM post_rank_stats r LEFT JOIN post_summaries s ON s.post_id=r.post_id
                WHERE s.post_id IS NULL
            """)
        conn.commit()

def _with_sync_lock(scope, fn):
    """Run fn(gc) under advisory lock; write sync_logs for scope."""
    with pool.connection() as lock_conn:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(860601)")
            got_lock = cur.fetchone()[0]
        lock_conn.commit()
        if not got_lock:
            return {"ok": False, "message": "已有同步正在运行，请稍后再试。"}
        log_id = log_start(scope)
        try:
            gc = get_gc()
            msg, errors = fn(gc)
            if errors:
                msg = msg + " 错误：" + " | ".join(errors[:20])
                log_finish(log_id, "partial", msg)
            else:
                log_finish(log_id, "success", msg)
            return {"ok": True, "message": msg}
        except Exception as e:
            log_finish(log_id, "failed", str(e))
            raise
        finally:
            with lock_conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(860601)")
            lock_conn.commit()

def run_sync_projects():
    """Only sync 交教会帖文 + 邀约上线 (project_items)."""
    def _run(gc):
        church_count, church_errors = sync_project_from_config(gc, CHURCH_CONFIG_SHEET_NAME, "church", False)
        invite_online_count, invite_online_errors = sync_project_from_config(
            gc, INVITE_ONLINE_CONFIG_SHEET_NAME, "invite_online", True
        )
        errors = church_errors + invite_online_errors
        msg = f"交教会 {church_count} 行；邀约上线 {invite_online_count} 行。"
        return msg, errors
    return _with_sync_lock("projects", _run)

def run_sync_all():
    def _run(gc):
        sync_pages(gc)
        summary_count, summary_errors = sync_summaries(gc)
        church_count, church_errors = sync_project_from_config(gc, CHURCH_CONFIG_SHEET_NAME, "church", False)
        invite_online_count, invite_online_errors = sync_project_from_config(
            gc, INVITE_ONLINE_CONFIG_SHEET_NAME, "invite_online", True
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT page_code,admin_name,sheet_url FROM pages WHERE enabled=true")
                cols = [d.name for d in cur.description]
                pages = [dict(zip(cols, row)) for row in cur.fetchall()]
        rank_total = 0
        rank_errors = []
        for page in pages:
            try:
                rank_total += sync_rank_for_page(gc, page)
            except Exception as e:
                rank_errors.append(f"{page.get('page_code')}: {e}")
        refresh_unmatched()
        errors = summary_errors + church_errors + invite_online_errors + rank_errors
        msg = (
            f"专页 {len(pages)} 个；汇总 {summary_count} 行；排行 {rank_total} 行；"
            f"交教会 {church_count} 行；邀约上线 {invite_online_count} 行。"
        )
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
