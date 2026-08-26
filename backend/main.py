import os
import re
import hashlib
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Optional, Any
import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from psycopg.types.json import Jsonb
from db import fetch_all, fetch_one, execute, pool, ensure_schema
from sync import run_sync_all, run_sync_projects, run_sync_foreign

USER_PASSWORD = os.environ.get("USER_PASSWORD", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
FACEBOOK_ACCESS_TOKEN = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")

app = FastAPI(title="Post Dashboard V11")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup():
    ensure_schema()

def add_month(year, month, delta):
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1

def church_cycle_paris(offset=0):
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    if today.day >= 23:
        sy, sm = today.year, today.month
    else:
        sy, sm = add_month(today.year, today.month, -1)
    sy, sm = add_month(sy, sm, offset)
    ey, em = add_month(sy, sm, 1)
    return date(sy, sm, 23), date(ey, em, 22)

def make_user_token():
    return hashlib.sha256(f"{USER_PASSWORD}:{ADMIN_TOKEN}".encode()).hexdigest()

def require_user(x_user_token: Optional[str] = Header(default=None)):
    if not x_user_token or x_user_token != make_user_token():
        raise HTTPException(status_code=401, detail="未登录")

def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="管理员密码错误")

class LoginBody(BaseModel):
    password: str

class SettingsBody(BaseModel):
    value: dict[str, Any]

class QueryTextBody(BaseModel):
    text: str = ""
    admin: str = "__all__"
    page_code: Optional[str] = None
    limit: int = 5000

def default_ui():
    return {
        "version":"v12",
        "columnsLayoutVersion": 15,
        "view":"table",
        "fontSize":13,"rowHeight":42,"imageSize":72,"textLimit":80,"drawerWidth":520,
        "showGrid":True,"headerBg":"#f8fafc","headerColor":"#111827","textColor":"#111827","gridColor":"#e5e7eb","stripeBg":"#ffffff","hoverBg":"#eef6ff",
        "globalMinLeads":2,"adminMinLeads":{},"genderMode":"count_percent",
        "landscape":{"ratio":"16/9","avatar":True,"dates":True,"gender":True,"metrics":True,"engagement":True,"pageType":True,"summary":True,"buttons":True},
        "portrait":{"ratio":"9/16","avatar":True,"dates":True,"gender":True,"metrics":True,"engagement":False,"pageType":True,"summary":False,"buttons":True},
        "columns": []
    }

@app.get("/api/health")
def health(): return {"ok": True}

@app.post("/api/auth/user")
def user_login(body: LoginBody):
    if body.password != USER_PASSWORD: raise HTTPException(status_code=401, detail="密码错误")
    return {"token": make_user_token()}

@app.post("/api/auth/admin")
def admin_login(body: LoginBody):
    if body.password != ADMIN_TOKEN: raise HTTPException(status_code=401, detail="管理员密码错误")
    return {"token": ADMIN_TOKEN}

@app.get("/api/avatar/{page_id}")
def avatar(page_id: str):
    if not page_id:
        raise HTTPException(status_code=404)
    url = f"https://graph.facebook.com/{page_id}/picture?width=120&height=120"
    if FACEBOOK_ACCESS_TOKEN:
        url += "&access_token=" + FACEBOOK_ACCESS_TOKEN
    try:
        r = httpx.get(url, follow_redirects=True, timeout=12)
        content_type = r.headers.get("content-type", "image/jpeg")
        if r.status_code >= 400 or not r.content:
            raise HTTPException(status_code=404)
        return Response(content=r.content, media_type=content_type, headers={"Cache-Control":"public, max-age=86400"})
    except Exception:
        raise HTTPException(status_code=404)

@app.get("/api/settings/ui")
def get_ui_settings(x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    row = fetch_one("SELECT value FROM system_settings WHERE key='ui'")
    merged = default_ui()
    if row and row.get("value"):
        merged.update(row["value"])
    return merged

@app.put("/api/settings/ui")
def put_ui_settings(body: SettingsBody, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    execute("""
        INSERT INTO system_settings(key,value,updated_at) VALUES('ui',%s,NOW())
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
    """, (Jsonb(body.value),))
    return {"ok": True}

@app.post("/api/settings/clear-sync-cache")
def clear_sync_cache(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    execute("TRUNCATE post_rank_stats, project_items, unmatched_posts RESTART IDENTITY")
    return {"ok": True}

@app.get("/api/admins")
def admins(x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    return fetch_all("SELECT name FROM admins ORDER BY name")

@app.get("/api/pages")
def pages(admin: Optional[str] = Query(default=None), x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    if admin and admin != "__all__":
        return fetch_all("SELECT page_code,admin_name,page_id,CASE WHEN page_id<>'' THEN '/api/avatar/'||page_id ELSE '' END AS page_avatar FROM pages WHERE enabled=true AND admin_name=%s ORDER BY page_code", (admin,))
    return fetch_all("SELECT page_code,admin_name,page_id,CASE WHEN page_id<>'' THEN '/api/avatar/'||page_id ELSE '' END AS page_avatar FROM pages WHERE enabled=true ORDER BY admin_name,page_code")

SORT_MAP = {
    "leads":"SUM(q.leads)","answers":"SUM(q.answers)","invites":"SUM(q.invites)","online":"SUM(q.online)","church":"SUM(q.church)","gained":"SUM(q.gained)",
    "male":"SUM(q.male)","female":"SUM(q.female)",
    "likes":"COALESCE(MAX(s.post_likes),0)","comments":"COALESCE(MAX(s.post_comments),0)","shares":"COALESCE(MAX(s.post_shares),0)",
    "post_likes":"COALESCE(MAX(s.post_likes),0)","post_comments":"COALESCE(MAX(s.post_comments),0)","post_shares":"COALESCE(MAX(s.post_shares),0)",
    "lead_date":"MIN(q.lead_date)","post_time":"MAX(s.post_time)"
}

def build_where(params, admin, page_code, date_type, start_date, end_date, use_date=True):
    where = ["1=1"]
    if admin and admin != "__all__": where.append("q.admin_name=%(admin)s"); params["admin"] = admin
    if page_code: where.append("q.page_code=%(page_code)s"); params["page_code"] = page_code
    if use_date:
        date_expr = "s.post_time::date" if date_type == "post" else "q.lead_date"
        if start_date: where.append(f"{date_expr} >= %(start_date)s"); params["start_date"] = start_date
        if end_date: where.append(f"{date_expr} <= %(end_date)s"); params["end_date"] = end_date
    return " AND ".join(where)

def common_sql(base_from, where_sql, order_sql, post_id_expr="q.post_id"):
    """Aggregate post rows. post_id_expr: q.post_id (rank-driven) or ids.post_id (project-driven)."""
    return f"""
        SELECT
            COALESCE(MIN(q.page_code), MIN(p_s.page_code), '') AS page_code,
            COALESCE(MIN(q.admin_name), MIN(p_s.admin_name), '') AS admin_name,
            COALESCE(MAX(NULLIF(p.page_id,'')), MAX(NULLIF(p_s.page_id,'')), MAX(NULLIF(s.page_id,'')), '') AS page_id,
            CASE WHEN COALESCE(MAX(NULLIF(p.page_id,'')), MAX(NULLIF(p_s.page_id,'')), MAX(NULLIF(s.page_id,'')), '') <> ''
                 THEN '/api/avatar/' || COALESCE(MAX(NULLIF(p.page_id,'')), MAX(NULLIF(p_s.page_id,'')), MAX(NULLIF(s.page_id,'')), '')
                 ELSE '' END AS page_avatar,
            {post_id_expr} AS post_id,
            COALESCE(MAX(NULLIF(q.post_link,'')), COALESCE(MAX(s.post_link), '')) AS post_link,
            MIN(q.lead_date) AS lead_date,
            COALESCE(SUM(q.male),0) AS male, COALESCE(SUM(q.female),0) AS female,
            COALESCE(SUM(q.leads),0) AS leads, COALESCE(SUM(q.answers),0) AS answers,
            COALESCE(SUM(q.invites),0) AS invites, COALESCE(SUM(q.online),0) AS online,
            COALESCE(SUM(q.church),0) AS church, COALESCE(SUM(q.gained),0) AS gained,
            MAX(s.post_time) AS post_time,
            COALESCE(MAX(s.display_media), '') AS display_media,
            COALESCE(MAX(s.page_post_type), '') AS page_post_type,
            COALESCE(MAX(s.post_likes), 0) AS post_likes,
            COALESCE(MAX(s.post_comments), 0) AS post_comments,
            COALESCE(MAX(s.post_shares), 0) AS post_shares,
            COALESCE(MAX(s.post_type), '') AS post_type,
            COALESCE(MAX(s.post_info), '') AS post_info,
            COALESCE(MAX(s.post_info_translation), '') AS post_info_translation,
            COALESCE(MAX(s.post_ocr), '') AS post_ocr,
            COALESCE(MAX(s.post_ocr_translation), '') AS post_ocr_translation,
            COALESCE(MAX(s.video_original), '') AS video_original,
            COALESCE(MAX(s.video_translation), '') AS video_translation,
            COALESCE(MAX(s.image_link), '') AS image_link,
            COALESCE(MAX(s.summary_source_name), '') AS summary_source_name,
            COALESCE(MAX(s.summary_source_sheet), '') AS summary_source_sheet
        {base_from}
        LEFT JOIN post_summaries s ON s.post_id={post_id_expr}
        LEFT JOIN pages p ON p.page_code=q.page_code AND p.admin_name=q.admin_name
        LEFT JOIN pages p_s ON NULLIF(s.page_id,'') IS NOT NULL AND p_s.page_id=s.page_id
        WHERE {where_sql}
        GROUP BY {post_id_expr}
        {order_sql}
        LIMIT %(limit)s OFFSET %(offset)s
    """

def count_sql(base_from, where_sql, post_id_expr="q.post_id"):
    return f"""
        SELECT COUNT(*) AS total FROM (
            SELECT {post_id_expr}
            {base_from}
            LEFT JOIN post_summaries s ON s.post_id={post_id_expr}
            LEFT JOIN pages p ON p.page_code=q.page_code AND p.admin_name=q.admin_name
            LEFT JOIN pages p_s ON NULLIF(s.page_id,'') IS NOT NULL AND p_s.page_id=s.page_id
            WHERE {where_sql}
            GROUP BY {post_id_expr}
            HAVING COALESCE(SUM(q.leads),0) >= %(min_leads)s
        ) t
    """

def _admin_page_where(where, params, admin, page_code, post_id_expr="q.post_id"):
    """Filter by admin/page; when rank row missing, fall back to summary→pages."""
    if admin and admin != "__all__":
        where.append(f"""(
            q.admin_name=%(admin)s
            OR (
                q.admin_name IS NULL AND EXISTS (
                    SELECT 1 FROM post_summaries s2
                    JOIN pages p2 ON NULLIF(p2.page_id,'') IS NOT NULL AND p2.page_id=s2.page_id
                    WHERE s2.post_id={post_id_expr} AND p2.admin_name=%(admin)s
                )
            )
        )""")
        params["admin"] = admin
    if page_code:
        where.append(f"""(
            q.page_code=%(page_code)s
            OR (
                q.page_code IS NULL AND EXISTS (
                    SELECT 1 FROM post_summaries s2
                    JOIN pages p2 ON NULLIF(p2.page_id,'') IS NOT NULL AND p2.page_id=s2.page_id
                    WHERE s2.post_id={post_id_expr} AND p2.page_code=%(page_code)s
                )
            )
        )""")
        params["page_code"] = page_code

@app.get("/api/posts")
def posts(admin: str="__all__", date_type: str="lead", start_date: Optional[date]=None, end_date: Optional[date]=None, page_code: Optional[str]=None, sort_by: Optional[str]=None, sort_dir: str="desc", min_leads: int=Query(2, ge=0), limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    params={"limit":limit,"offset":offset,"min_leads":min_leads}
    where_sql=build_where(params, admin, page_code, date_type, start_date, end_date, True)
    order_col=SORT_MAP.get(sort_by or "", "MAX(s.post_time)" if date_type=="post" else "MIN(q.lead_date)")
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    base="FROM post_rank_stats q"
    order=f"HAVING COALESCE(SUM(q.leads),0)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, q.post_id DESC"
    total=fetch_one(count_sql(base, where_sql), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order), params)}

@app.get("/api/ranking")
def ranking(metric: str="leads", sort_by: Optional[str]=None, sort_dir: str="desc", start_date: Optional[date]=None, end_date: Optional[date]=None, admin: str="__all__", page_code: Optional[str]=None, min_leads: int=Query(2, ge=0), limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    today=datetime.utcnow().date(); start_date=start_date or today; end_date=end_date or today
    params={"limit":limit,"offset":offset,"min_leads":min_leads}
    where_sql=build_where(params, admin, page_code, "lead", start_date, end_date, True)
    base="FROM post_rank_stats q"
    order_col=SORT_MAP.get(sort_by or metric, "SUM(q.leads)")
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    order=f"HAVING COALESCE(SUM(q.leads),0)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, q.post_id DESC"
    total=fetch_one(count_sql(base, where_sql), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order), params)}

@app.get("/api/project-posts")
def project_posts(project: str, mode: str="all", start_date: Optional[date]=None, end_date: Optional[date]=None, admin: str="__all__", page_code: Optional[str]=None, sort_by: Optional[str]=None, sort_dir: str="desc", min_leads: int=Query(0, ge=0), limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
    """交教会等：以 project_items 为池（按 project_date），再关联排行/汇总。"""
    require_user(x_user_token)
    today=datetime.utcnow().date()
    if project == "church" and (not start_date or not end_date):
        cycle_start, cycle_end = church_cycle_paris(0)
        if not start_date: start_date = cycle_start
        if not end_date: end_date = cycle_end
    else:
        if not start_date: start_date = today
        if not end_date: end_date = today
    params={"limit":limit,"offset":offset,"min_leads":min_leads,"project":project,"start_date":start_date,"end_date":end_date}
    pool_extra = "AND pi.is_online=true" if mode=="online" else ""
    # 以 project_items 为驱动，避免只同步了项目表、或帖文不在「帖文排行」时查不到
    base = f"""FROM (
        SELECT DISTINCT pi.post_id
        FROM project_items pi
        WHERE pi.project_name=%(project)s
          AND pi.project_date IS NOT NULL
          AND pi.project_date >= %(start_date)s
          AND pi.project_date <= %(end_date)s
          {pool_extra}
    ) ids
    LEFT JOIN post_rank_stats q ON q.post_id = ids.post_id"""
    post_id_expr = "ids.post_id"
    where = ["1=1"]
    _admin_page_where(where, params, admin, page_code, post_id_expr)
    where_sql = " AND ".join(where)
    if project=="church": default_sort="COALESCE(SUM(q.church),0)"
    elif mode=="online": default_sort="COALESCE(SUM(q.online),0)"
    else: default_sort="COALESCE(SUM(q.invites),0)"
    order_col=SORT_MAP.get(sort_by or "", default_sort)
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    order=f"HAVING COALESCE(SUM(q.leads),0)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, {post_id_expr} DESC"
    total=fetch_one(count_sql(base, where_sql, post_id_expr), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order, post_id_expr), params)}

@app.get("/api/overview")
def overview(metric: str="invites", date_type: str="invite", sort_by: Optional[str]=None, sort_dir: str="desc", start_date: Optional[date]=None, end_date: Optional[date]=None, admin: str="__all__", page_code: Optional[str]=None, limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
    """邀约/上线总览：默认按 project_items.project_date；发帖日期则在邀约池上按 post_time 筛。"""
    require_user(x_user_token)
    today=datetime.utcnow().date(); start_date=start_date or today; end_date=end_date or today
    metric_col = "online" if metric=="online" else "invites"
    params={"limit":limit,"offset":offset,"min_leads":0,"start_date":start_date,"end_date":end_date}
    online_extra = "AND pi.is_online=true" if metric_col=="online" else ""
    post_id_expr = "ids.post_id"
    where = ["1=1"]
    if date_type == "post":
        # 邀约/上线池内全部 post_id，再按汇总发帖日筛选
        base = f"""FROM (
            SELECT DISTINCT pi.post_id
            FROM project_items pi
            WHERE pi.project_name='invite_online'
              {online_extra}
        ) ids
        LEFT JOIN post_rank_stats q ON q.post_id = ids.post_id"""
        where.append("s.post_time::date >= %(start_date)s")
        where.append("s.post_time::date <= %(end_date)s")
    else:
        base = f"""FROM (
            SELECT DISTINCT pi.post_id
            FROM project_items pi
            WHERE pi.project_name='invite_online'
              AND pi.project_date IS NOT NULL
              AND pi.project_date >= %(start_date)s
              AND pi.project_date <= %(end_date)s
              {online_extra}
        ) ids
        LEFT JOIN post_rank_stats q ON q.post_id = ids.post_id"""
    _admin_page_where(where, params, admin, page_code, post_id_expr)
    where_sql = " AND ".join(where)
    order_col=SORT_MAP.get(sort_by or metric_col, f"COALESCE(SUM(q.{metric_col}),0)")
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    order=f"HAVING COALESCE(SUM(q.leads),0)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, {post_id_expr} DESC"
    total=fetch_one(count_sql(base, where_sql, post_id_expr), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order, post_id_expr), params)}


def _split_query_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]


def _first_cell(line: str) -> str:
    if "\t" in line:
        return line.split("\t", 1)[0].strip()
    return line.strip()


def _post_id_variants(raw: str) -> list[str]:
    """帖文ID查询：无 # 时自动补上；同时保留无 # 变体以便兼容库内两种写法。"""
    s = (raw or "").strip()
    if not s:
        return []
    # 去掉首尾空白与包裹引号
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    if not s:
        return []
    variants = [s]
    if s.startswith("#"):
        bare = s[1:].strip()
        if bare:
            variants.append(bare)
            variants.append("#" + bare)
    else:
        variants.append("#" + s)
    # 去重保序
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _normalize_link(link: str) -> str:
    s = (link or "").strip()
    if not s:
        return ""
    # 从混杂文本中提取 URL
    m = re.search(r"https?://[^\s\t]+", s, flags=re.I)
    if m:
        s = m.group(0)
    s = s.rstrip(").,;，。；]")
    while s.endswith("/"):
        s = s[:-1]
    return s


def _parse_lead_row(line: str) -> Optional[tuple[str, str]]:
    """解析两列：线索ID、加友渠道。支持 Tab / 多空格 / 逗号分隔。"""
    s = (line or "").strip()
    if not s:
        return None
    if "\t" in s:
        parts = [p.strip() for p in s.split("\t")]
    elif "，" in s or "," in s:
        parts = [p.strip() for p in re.split(r"[,，]", s, maxsplit=1)]
    elif re.search(r"\s{2,}", s):
        parts = [p.strip() for p in re.split(r"\s{2,}", s, maxsplit=1)]
    else:
        # 单空格：第一段为线索ID，其余为渠道
        m = re.match(r"^(\S+)\s+(.+)$", s)
        parts = [m.group(1), m.group(2)] if m else [s]
    lead_id = (parts[0] if parts else "").strip()
    friend_channel = (parts[1] if len(parts) > 1 else "").strip()
    if not lead_id:
        return None
    return lead_id, friend_channel


def _posts_by_ordered_ids(post_ids: list[str], admin: str = "__all__", page_code: Optional[str] = None, limit: int = 5000) -> list[dict]:
    """按给定 post_id 列表取帖文详情，保持输入顺序；仅返回库中存在的帖文。"""
    ordered: list[str] = []
    seen: set[str] = set()
    for pid in post_ids:
        if pid and pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    if not ordered:
        return []
    limit = max(1, min(int(limit or 5000), 5000))
    ordered = ordered[:limit]
    params: dict[str, Any] = {"limit": limit, "offset": 0, "min_leads": 0, "ids": ordered}
    base = """FROM (
        SELECT unnest(%(ids)s::text[]) AS post_id
    ) ids
    LEFT JOIN post_rank_stats q ON q.post_id = ids.post_id"""
    post_id_expr = "ids.post_id"
    where = [
        f"""(
            EXISTS (SELECT 1 FROM post_rank_stats r WHERE r.post_id = {post_id_expr})
            OR EXISTS (SELECT 1 FROM post_summaries s2 WHERE s2.post_id = {post_id_expr})
            OR EXISTS (SELECT 1 FROM project_items pi2 WHERE pi2.post_id = {post_id_expr})
        )"""
    ]
    _admin_page_where(where, params, admin, page_code, post_id_expr)
    where_sql = " AND ".join(where)
    order = (
        f"HAVING COALESCE(SUM(q.leads),0)>=%(min_leads)s "
        f"ORDER BY array_position(%(ids)s::text[], {post_id_expr}) NULLS LAST"
    )
    return fetch_all(common_sql(base, where_sql, order, post_id_expr), params)


def _resolve_existing_post_ids(candidates: list[str]) -> set[str]:
    if not candidates:
        return set()
    rows = fetch_all(
        """
        SELECT post_id FROM post_rank_stats WHERE post_id = ANY(%(ids)s)
        UNION
        SELECT post_id FROM post_summaries WHERE post_id = ANY(%(ids)s)
        UNION
        SELECT post_id FROM project_items WHERE post_id = ANY(%(ids)s)
        """,
        {"ids": candidates},
    )
    return {r["post_id"] for r in rows if r.get("post_id")}


def _query_response(rows: list[dict], raw: int, recognized: int, unmatched: list[str]) -> dict:
    return {
        "total": len(rows),
        "rows": rows,
        "unmatched": unmatched,
        "stats": {
            "raw": raw,
            "recognized": recognized,
            "returned": len(rows),
            "unmatched": len(unmatched),
        },
    }


@app.post("/api/query/by-post-id")
def query_by_post_id(body: QueryTextBody, x_user_token: Optional[str] = Header(default=None)):
    """按帖文ID批量查询；输入无 # 时自动补上。"""
    require_user(x_user_token)
    raw_lines = _split_query_lines(body.text)
    recognized_inputs: list[str] = []
    for line in raw_lines:
        cell = _first_cell(line)
        if cell:
            recognized_inputs.append(cell)

    if not recognized_inputs:
        return _query_response([], len(raw_lines), 0, [])

    all_candidates: list[str] = []
    input_to_variants: list[list[str]] = []
    for raw in recognized_inputs:
        variants = _post_id_variants(raw)
        if variants and not any(v.startswith("#") for v in variants):
            variants.append("#" + variants[0])
        input_to_variants.append(variants)
        all_candidates.extend(variants)

    existing = _resolve_existing_post_ids(all_candidates)
    resolved_ids: list[str] = []
    unmatched: list[str] = []
    for raw, variants in zip(recognized_inputs, input_to_variants):
        preferred = next((v for v in variants if v in existing), None)
        if preferred:
            resolved_ids.append(preferred)
        else:
            unmatched.append(raw)

    rows = _posts_by_ordered_ids(resolved_ids, body.admin, body.page_code, body.limit)
    returned_ids = {r.get("post_id") for r in rows if r.get("post_id")}
    # 库中有记录但被管理员/专页过滤掉的，也计入未命中
    for raw, variants in zip(recognized_inputs, input_to_variants):
        preferred = next((v for v in variants if v in existing), None)
        if preferred and preferred not in returned_ids and raw not in unmatched:
            unmatched.append(raw)
    return _query_response(rows, len(raw_lines), len(recognized_inputs), unmatched)


@app.post("/api/query/by-post-link")
def query_by_post_link(body: QueryTextBody, x_user_token: Optional[str] = Header(default=None)):
    """按帖文链接批量查询。"""
    require_user(x_user_token)
    raw_lines = _split_query_lines(body.text)
    links: list[str] = []
    for line in raw_lines:
        link = _normalize_link(line if "http" in line.lower() else _first_cell(line))
        if not link and line:
            link = _normalize_link(line)
        if link:
            links.append(link)

    if not links:
        return _query_response([], len(raw_lines), 0, [])

    link_set: list[str] = []
    seen_l: set[str] = set()
    for lk in links:
        for cand in (lk, lk + "/"):
            if cand not in seen_l:
                seen_l.add(cand)
                link_set.append(cand)
    norm_links = list({lk.rstrip("/") for lk in link_set if lk})

    found = fetch_all(
        """
        SELECT post_id, post_link FROM post_summaries
        WHERE NULLIF(post_link,'') IS NOT NULL
          AND (
            post_link = ANY(%(links)s)
            OR RTRIM(post_link, '/') = ANY(%(norm_links)s)
          )
        UNION
        SELECT post_id, post_link FROM post_rank_stats
        WHERE NULLIF(post_link,'') IS NOT NULL
          AND (
            post_link = ANY(%(links)s)
            OR RTRIM(post_link, '/') = ANY(%(norm_links)s)
          )
        """,
        {"links": link_set, "norm_links": norm_links},
    )
    link_to_posts: dict[str, list[str]] = {}
    for r in found:
        pid = r.get("post_id") or ""
        pl = (r.get("post_link") or "").rstrip("/")
        if not pid or not pl:
            continue
        link_to_posts.setdefault(pl, [])
        if pid not in link_to_posts[pl]:
            link_to_posts[pl].append(pid)

    ordered_ids: list[str] = []
    seen_p: set[str] = set()
    unmatched: list[str] = []
    for lk in links:
        key = lk.rstrip("/")
        pids = link_to_posts.get(key, [])
        if not pids:
            unmatched.append(lk)
            continue
        for pid in pids:
            if pid not in seen_p:
                seen_p.add(pid)
                ordered_ids.append(pid)

    rows = _posts_by_ordered_ids(ordered_ids, body.admin, body.page_code, body.limit)
    returned_ids = {r.get("post_id") for r in rows if r.get("post_id")}
    for lk in links:
        key = lk.rstrip("/")
        pids = link_to_posts.get(key, [])
        if pids and not any(pid in returned_ids for pid in pids) and lk not in unmatched:
            unmatched.append(lk)
    return _query_response(rows, len(raw_lines), len(links), unmatched)


@app.post("/api/query/by-lead-id")
def query_by_lead_id(body: QueryTextBody, x_user_token: Optional[str] = Header(default=None)):
    """按线索ID + 加友渠道批量查询关联帖文。两列：第一列线索ID，第二列加友渠道。"""
    require_user(x_user_token)
    raw_lines = _split_query_lines(body.text)
    items: list[tuple[str, str]] = []
    for line in raw_lines:
        parsed = _parse_lead_row(line)
        if parsed:
            items.append(parsed)

    if not items:
        return _query_response([], len(raw_lines), 0, [])

    value_rows = []
    params: dict[str, Any] = {}
    for i, (lead_id, channel) in enumerate(items):
        params[f"l{i}"] = lead_id
        params[f"c{i}"] = channel
        params[f"ord{i}"] = i
        value_rows.append(f"(%(ord{i})s::int, %(l{i})s::text, %(c{i})s::text)")
    values_sql = ", ".join(value_rows)
    matched = fetch_all(
        f"""
        SELECT v.ord, v.lead_id, v.friend_channel AS query_channel, pi.post_id, pi.friend_channel
        FROM (VALUES {values_sql}) AS v(ord, lead_id, friend_channel)
        JOIN project_items pi ON pi.lead_id = v.lead_id
          AND (
            NULLIF(v.friend_channel, '') IS NULL
            OR pi.friend_channel = v.friend_channel
          )
        WHERE NULLIF(pi.post_id, '') IS NOT NULL
        ORDER BY v.ord, pi.id
        """,
        params,
    )

    matched_ords: set[int] = set()
    ordered_ids: list[str] = []
    seen_p: set[str] = set()
    lead_meta: dict[str, dict[str, str]] = {}
    for r in matched:
        try:
            matched_ords.add(int(r.get("ord")))
        except Exception:
            pass
        pid = r.get("post_id")
        if not pid:
            continue
        if pid not in seen_p:
            seen_p.add(pid)
            ordered_ids.append(pid)
            lead_meta[pid] = {
                "query_lead_id": r.get("lead_id") or "",
                "query_friend_channel": r.get("query_channel") or r.get("friend_channel") or "",
            }

    unmatched: list[str] = []
    for i, (lead_id, channel) in enumerate(items):
        if i not in matched_ords:
            unmatched.append(f"{lead_id}\t{channel}" if channel else lead_id)

    rows = _posts_by_ordered_ids(ordered_ids, body.admin, body.page_code, body.limit)
    for row in rows:
        meta = lead_meta.get(row.get("post_id") or "", {})
        row["query_lead_id"] = meta.get("query_lead_id", "")
        row["query_friend_channel"] = meta.get("query_friend_channel", "")

    returned_ids = {r.get("post_id") for r in rows if r.get("post_id")}
    # 有匹配帖文但被管理员过滤的输入
    ord_to_pids: dict[int, list[str]] = {}
    for r in matched:
        try:
            o = int(r.get("ord"))
        except Exception:
            continue
        pid = r.get("post_id")
        if not pid:
            continue
        ord_to_pids.setdefault(o, []).append(pid)
    for i, (lead_id, channel) in enumerate(items):
        pids = ord_to_pids.get(i, [])
        label = f"{lead_id}\t{channel}" if channel else lead_id
        if pids and not any(pid in returned_ids for pid in pids) and label not in unmatched:
            unmatched.append(label)

    return _query_response(rows, len(raw_lines), len(items), unmatched)


REF_SORT_MAP = {
    "leads": "leads",
    "post_likes": "post_likes",
    "post_comments": "post_comments",
    "post_shares": "post_shares",
    "post_time": "post_time",
    "post_type": "post_type",
    "lang_label": "lang_label",
}


def _reference_where(params, lang, post_type, min_leads, start_date, end_date):
    where = ["1=1"]
    if lang:
        where.append("lang_label=%(lang)s")
        params["lang"] = lang
    if post_type:
        where.append("post_type=%(post_type)s")
        params["post_type"] = post_type
    where.append("COALESCE(leads,0) >= %(min_leads)s")
    params["min_leads"] = min_leads
    if start_date:
        where.append("post_time::date >= %(start_date)s")
        params["start_date"] = start_date
    if end_date:
        where.append("post_time::date <= %(end_date)s")
        params["end_date"] = end_date
    return " AND ".join(where)


@app.get("/api/reference/meta")
def reference_meta(lang: str = "", x_user_token: Optional[str] = Header(default=None)):
    """Lang tabs + post-type dropdown for 外语系参考. Isolated from /api/admins and /api/pages."""
    require_user(x_user_token)
    ensure_schema()
    langs = [r["lang_label"] for r in fetch_all(
        "SELECT lang_label FROM foreign_ref_posts GROUP BY lang_label ORDER BY MIN(id)"
    )]
    type_params: dict[str, Any] = {}
    type_where = "NULLIF(post_type,'') IS NOT NULL"
    if lang:
        type_where += " AND lang_label=%(lang)s"
        type_params["lang"] = lang
    post_types = [r["post_type"] for r in fetch_all(
        f"SELECT post_type FROM foreign_ref_posts WHERE {type_where} GROUP BY post_type ORDER BY post_type",
        type_params,
    )]
    return {"langs": langs, "post_types": post_types}


@app.get("/api/reference/posts")
def reference_posts(
    lang: str = "",
    post_type: str = "",
    min_leads: int = Query(0, ge=0),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = "desc",
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    x_user_token: Optional[str] = Header(default=None),
):
    """外语系参考：不走排行/项目/本语系汇总，不影响现有页签。"""
    require_user(x_user_token)
    ensure_schema()
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    where_sql = _reference_where(params, lang, post_type, min_leads, start_date, end_date)
    order_col = REF_SORT_MAP.get(sort_by or "leads", "leads")
    order_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
    total_row = fetch_one(f"SELECT COUNT(*) AS total FROM foreign_ref_posts WHERE {where_sql}", params)
    rows = fetch_all(
        f"""
        SELECT
            post_id,
            lang_label,
            lang_label AS page_code,
            ''::text AS admin_name,
            ''::text AS page_id,
            ''::text AS page_avatar,
            COALESCE(leads,0) AS leads,
            0::bigint AS invites,
            0::bigint AS online,
            0::bigint AS church,
            0::bigint AS male,
            0::bigint AS female,
            post_link,
            image_link,
            COALESCE(NULLIF(image_link,''), '') AS display_media,
            post_time,
            NULL::date AS lead_date,
            COALESCE(post_type, '') AS post_type,
            COALESCE(caption_original, '') AS caption_original,
            COALESCE(caption_zh, '') AS caption_zh,
            COALESCE(caption_original, '') AS post_info,
            COALESCE(caption_zh, '') AS post_info_translation,
            COALESCE(post_likes,0) AS post_likes,
            COALESCE(post_comments,0) AS post_comments,
            COALESCE(post_shares,0) AS post_shares,
            COALESCE(source_sheet, '') AS summary_source_sheet,
            lang_label AS summary_source_name,
            TRUE AS is_foreign_ref
        FROM foreign_ref_posts
        WHERE {where_sql}
        ORDER BY {order_col} {order_dir} NULLS LAST, id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    )
    return {"total": (total_row or {}).get("total", 0), "rows": rows}


@app.get("/api/sync/logs")
def sync_logs(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return fetch_all("SELECT * FROM sync_logs ORDER BY id DESC LIMIT 100")

@app.get("/api/unmatched")
def unmatched(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return fetch_all("SELECT * FROM unmatched_posts ORDER BY id DESC LIMIT 500")

@app.post("/api/sync/run")
def sync_run(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return run_sync_all()

@app.post("/api/sync/run/projects")
def sync_run_projects(x_admin_token: Optional[str] = Header(default=None)):
    """仅同步交教会帖文 + 邀约上线。"""
    require_admin(x_admin_token)
    return run_sync_projects()

@app.post("/api/sync/run/foreign")
def sync_run_foreign(x_admin_token: Optional[str] = Header(default=None)):
    """仅同步外语系参考。不改动排行/项目/本语系汇总。"""
    require_admin(x_admin_token)
    return run_sync_foreign()
