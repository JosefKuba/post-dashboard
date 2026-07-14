import os
import hashlib
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Optional, Any
import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from psycopg.types.json import Jsonb
from db import fetch_all, fetch_one, execute, pool
from sync import run_sync_all

USER_PASSWORD = os.environ.get("USER_PASSWORD", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
FACEBOOK_ACCESS_TOKEN = os.environ.get("FACEBOOK_ACCESS_TOKEN", "")

app = FastAPI(title="Post Dashboard V11")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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

def default_ui():
    return {
        "version":"v11",
        "view":"table",
        "fontSize":13,"rowHeight":42,"imageSize":72,"textLimit":80,"drawerWidth":560,
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

def common_sql(base_from, where_sql, order_sql):
    return f"""
        SELECT
            MIN(q.page_code) AS page_code,
            MIN(q.admin_name) AS admin_name,
            COALESCE(MAX(NULLIF(p.page_id,'')), '') AS page_id,
            CASE WHEN COALESCE(MAX(NULLIF(p.page_id,'')), '') <> '' THEN '/api/avatar/' || COALESCE(MAX(NULLIF(p.page_id,'')), '') ELSE '' END AS page_avatar,
            q.post_id,
            COALESCE(MAX(NULLIF(q.post_link,'')), COALESCE(MAX(s.post_link), '')) AS post_link,
            MIN(q.lead_date) AS lead_date,
            SUM(q.male) AS male, SUM(q.female) AS female, SUM(q.leads) AS leads, SUM(q.answers) AS answers,
            SUM(q.invites) AS invites, SUM(q.online) AS online, SUM(q.church) AS church, SUM(q.gained) AS gained,
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
        LEFT JOIN post_summaries s ON s.post_id=q.post_id
        LEFT JOIN pages p ON p.page_code=q.page_code AND p.admin_name=q.admin_name
        WHERE {where_sql}
        GROUP BY q.post_id
        {order_sql}
        LIMIT %(limit)s OFFSET %(offset)s
    """

def count_sql(base_from, where_sql):
    return f"SELECT COUNT(*) AS total FROM (SELECT q.post_id {base_from} LEFT JOIN post_summaries s ON s.post_id=q.post_id LEFT JOIN pages p ON p.page_code=q.page_code AND p.admin_name=q.admin_name WHERE {where_sql} GROUP BY q.post_id HAVING SUM(q.leads) >= %(min_leads)s) t"

@app.get("/api/posts")
def posts(admin: str="__all__", date_type: str="lead", start_date: Optional[date]=None, end_date: Optional[date]=None, page_code: Optional[str]=None, sort_by: Optional[str]=None, sort_dir: str="desc", min_leads: int=Query(2, ge=0), limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    params={"limit":limit,"offset":offset,"min_leads":min_leads}
    where_sql=build_where(params, admin, page_code, date_type, start_date, end_date, True)
    order_col=SORT_MAP.get(sort_by or "", "MAX(s.post_time)" if date_type=="post" else "MIN(q.lead_date)")
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    base="FROM post_rank_stats q"
    order=f"HAVING SUM(q.leads)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, q.post_id DESC"
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
    order=f"HAVING SUM(q.leads)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, q.post_id DESC"
    total=fetch_one(count_sql(base, where_sql), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order), params)}

@app.get("/api/project-posts")
def project_posts(project: str, mode: str="all", start_date: Optional[date]=None, end_date: Optional[date]=None, admin: str="__all__", page_code: Optional[str]=None, sort_by: Optional[str]=None, sort_dir: str="desc", min_leads: int=Query(0, ge=0), limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
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
    base=f"FROM post_rank_stats q"
    where=[f"q.post_id IN (SELECT DISTINCT pi.post_id FROM project_items pi WHERE pi.project_name=%(project)s AND pi.project_date >= %(start_date)s AND pi.project_date <= %(end_date)s {pool_extra})"]
    if admin and admin != "__all__": where.append("q.admin_name=%(admin)s"); params["admin"]=admin
    if page_code: where.append("q.page_code=%(page_code)s"); params["page_code"]=page_code
    where_sql=" AND ".join(where)
    if project=="church": default_sort="SUM(q.church)"
    elif mode=="online": default_sort="SUM(q.online)"
    else: default_sort="SUM(q.invites)"
    order_col=SORT_MAP.get(sort_by or "", default_sort)
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    order=f"HAVING SUM(q.leads)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, q.post_id DESC"
    total=fetch_one(count_sql(base, where_sql), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order), params)}

@app.get("/api/overview")
def overview(metric: str="invites", date_type: str="invite", sort_by: Optional[str]=None, sort_dir: str="desc", start_date: Optional[date]=None, end_date: Optional[date]=None, admin: str="__all__", page_code: Optional[str]=None, limit: int=Query(500, ge=1, le=5000), offset: int=Query(0, ge=0), x_user_token: Optional[str] = Header(default=None)):
    require_user(x_user_token)
    today=datetime.utcnow().date(); start_date=start_date or today; end_date=end_date or today
    metric_col = "online" if metric=="online" else "invites"
    params={"limit":limit,"offset":offset,"min_leads":0,"start_date":start_date,"end_date":end_date}
    where=[]
    if admin and admin != "__all__": where.append("q.admin_name=%(admin)s"); params["admin"]=admin
    if page_code: where.append("q.page_code=%(page_code)s"); params["page_code"]=page_code
    if date_type == "post":
        base="FROM post_rank_stats q"
        where.append("s.post_time::date >= %(start_date)s")
        where.append("s.post_time::date <= %(end_date)s")
    else:
        extra = "AND pi.is_online=true" if metric_col=="online" else ""
        base=f"""FROM post_rank_stats q"""
        where.append(f"q.post_id IN (SELECT DISTINCT pi.post_id FROM project_items pi WHERE pi.project_name='invite_online' AND pi.project_date >= %(start_date)s AND pi.project_date <= %(end_date)s {extra})")
    where_sql=" AND ".join(where) if where else "1=1"
    order_col=SORT_MAP.get(sort_by or metric_col, f"SUM(q.{metric_col})")
    order_dir="ASC" if sort_dir.lower()=="asc" else "DESC"
    order=f"HAVING SUM(q.leads)>=%(min_leads)s ORDER BY {order_col} {order_dir} NULLS LAST, q.post_id DESC"
    total=fetch_one(count_sql(base, where_sql), params)["total"]
    return {"total": total, "rows": fetch_all(common_sql(base, where_sql, order), params)}

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
