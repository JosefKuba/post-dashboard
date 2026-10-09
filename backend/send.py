"""入库外语系参考 TOP30 → Teams。每个语系一条 HTML 表格消息，引流最高 30 条；语系之间间隔 1 秒；失败最多重试 5 次。

按 send.py 原格式调用：
  POST {TEAMS_SEND_URL}
  headers: Content-Type, x-api-key
  json: {chat_id, content}

用法：
  python send.py
  python send.py --date 2026-08-25
  python send.py --dry-run
"""
import argparse
import html
import os
import ssl
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

import httpx

from db import ensure_schema, fetch_all

TOP_N_DEFAULT = 30
SEND_PAUSE_SECONDS = 1
SEND_MAX_ATTEMPTS = 5


def _env(name, default=""):
    v = os.environ.get(name)
    return default if v is None or str(v).strip() == "" else str(v).strip()


def _truthy(v, default=False):
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def report_date(offset_days=1, explicit=None):
    if explicit:
        return datetime.strptime(explicit, "%Y-%m-%d").date()
    tz_name = _env("REPORT_TZ") or _env("TZ") or "UTC"
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        today = datetime.now().date()
    return today - timedelta(days=offset_days)


def fetch_top_by_lang(day, top_n=TOP_N_DEFAULT):
    ensure_schema()
    return fetch_all(
        """
        WITH ranked AS (
            SELECT
                lang_label,
                COALESCE(leads, 0) AS leads,
                COALESCE(post_link, '') AS post_link,
                post_id,
                ROW_NUMBER() OVER (
                    PARTITION BY lang_label
                    ORDER BY COALESCE(leads, 0) DESC, id DESC
                ) AS rn,
                MIN(id) OVER (PARTITION BY lang_label) AS lang_ord
            FROM foreign_ref_posts
            WHERE register_date = %(register_date)s
        )
        SELECT lang_label, leads, post_link, post_id, rn
        FROM ranked
        WHERE rn <= %(top_n)s
        ORDER BY lang_ord, rn
        """,
        {"register_date": day, "top_n": int(top_n)},
    )


def group_rows(rows):
    groups = OrderedDict()
    for r in rows:
        key = r.get("lang_label") or "未分组"
        groups.setdefault(key, []).append(r)
    return groups


def _html_link(url):
    url = (url or "").strip()
    if not url:
        return "-"
    safe = html.escape(url, quote=True)
    return f'<a href="{safe}">{html.escape(url)}</a>'


def _html_table_message(day, top_n, lang, items):
    rows = ["<tr><th>排名</th><th>引流量</th><th>帖文链接</th></tr>"]
    for i, r in enumerate(items, 1):
        rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{int(r.get('leads') or 0)}</td>"
            f"<td>{_html_link(r.get('post_link'))}</td>"
            "</tr>"
        )
    return (
        f"<p><b>外语系参考 {html.escape(day.isoformat())} 入库 TOP{top_n}</b></p>"
        f"<p><b>{html.escape(lang)}</b>（{len(items)}）</p>"
        "<table>"
        f"{''.join(rows)}"
        "</table>"
    )


def build_html(day, groups, top_n):
    if not groups:
        return f"<p>外语系参考 {html.escape(day.isoformat())} 入库 TOP{top_n}</p><p>该日无入库帖文。</p>"
    parts = []
    for i, (lang, items) in enumerate(groups.items()):
        if i:
            parts.append("<br><br>")
        parts.append(_html_table_message(day, top_n, lang, items))
    return "".join(parts)


def _utf8_len(s):
    return len((s or "").encode("utf-8"))


def split_html_messages(day, groups, top_n):
    """One language = one HTML table message, all rows included."""
    if not groups:
        return [build_html(day, groups, top_n)]
    return [_html_table_message(day, top_n, lang, items) for lang, items in groups.items() if items]


def _ssl_verify(verify_ssl):
    if verify_ssl:
        return True
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _url_with_scheme(url, scheme):
    p = urlparse(url)
    return urlunparse(p._replace(scheme=scheme))


def send_message(content):
    url = _env("TEAMS_SEND_URL")
    api_key = _env("TEAMS_API_KEY")
    chat_id = _env("TEAMS_CHAT_ID")
    if not url or not api_key or not chat_id:
        raise RuntimeError("缺少 TEAMS_SEND_URL / TEAMS_API_KEY / TEAMS_CHAT_ID，请写在 .env")
    verify_ssl = _truthy(os.environ.get("TEAMS_VERIFY_SSL"), default=False)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }
    payload = {"chat_id": chat_id, "content": content}
    urls = [url]
    parsed = urlparse(url)
    if parsed.scheme == "https":
        urls.append(_url_with_scheme(url, "http"))
    elif parsed.scheme == "http":
        urls.append(_url_with_scheme(url, "https"))
    last_err = None
    for u in urls:
        try:
            with httpx.Client(verify=_ssl_verify(verify_ssl), timeout=30.0, trust_env=False) as client:
                res = client.post(u, headers=headers, json=payload)
            try:
                data = res.json()
            except Exception:
                data = {"text": res.text}
            if res.status_code >= 400:
                raise RuntimeError(f"Teams 发送失败 HTTP {res.status_code}: {data}")
            if u != url:
                print(f"Teams 已改用 {urlparse(u).scheme.upper()} 发送", flush=True)
            return data
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            print(f"Teams 连接失败 {u}: {e!r}", flush=True)
            continue
    raise RuntimeError(f"Teams 发送失败（HTTPS/HTTP 均不可用）: {last_err!r}") from last_err


def send_message_with_retry(content, attempts=SEND_MAX_ATTEMPTS):
    last_err = None
    for n in range(1, attempts + 1):
        try:
            data = send_message(content)
            if n > 1:
                print(f"第 {n} 次发送成功", flush=True)
            return data
        except Exception as e:
            last_err = e
            print(f"第 {n}/{attempts} 次发送失败: {e}", flush=True)
            if n < attempts:
                print(f"等待 {SEND_PAUSE_SECONDS} 秒后重试", flush=True)
                time.sleep(SEND_PAUSE_SECONDS)
    raise RuntimeError(f"连续 {attempts} 次发送失败: {last_err}") from last_err


def run(day=None, top_n=TOP_N_DEFAULT, dry_run=False):
    day = day or report_date()
    rows = fetch_top_by_lang(day, top_n)
    groups = group_rows(rows)
    results = []
    contents = split_html_messages(day, groups, top_n)
    for i, content in enumerate(contents, 1):
        nbytes = _utf8_len(content)
        print(f"准备发送 {i}/{len(contents)} {nbytes} 字节", flush=True)
        if dry_run:
            print(f"----- message {i}/{len(contents)} -----")
            print(content)
            results.append({"dry_run": True, "bytes": nbytes})
            continue
        results.append(send_message_with_retry(content))
        if i < len(contents):
            print(f"等待 {SEND_PAUSE_SECONDS} 秒后发送下一条", flush=True)
            time.sleep(SEND_PAUSE_SECONDS)
    return {
        "ok": True,
        "date": day.isoformat(),
        "langs": len(groups),
        "rows": len(rows),
        "messages": len(contents),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="发送当日入库外语系参考 TOP30 到 Teams")
    parser.add_argument("--date", help="入库日期 YYYY-MM-DD，默认昨天")
    parser.add_argument("--top", type=int, default=TOP_N_DEFAULT, help="每个语系取前 N 条，默认 30")
    parser.add_argument("--dry-run", action="store_true", help="只打印内容，不发送")
    parser.add_argument("--ping", action="store_true", help="只发一条测试文本，验证接口")
    args = parser.parse_args()
    if args.ping:
        print(send_message("你好！这是一条由 Python 客户端触发的通知。"))
        return
    out = run(day=report_date(explicit=args.date) if args.date else report_date(), top_n=args.top, dry_run=args.dry_run)
    print(out)


if __name__ == "__main__":
    main()
