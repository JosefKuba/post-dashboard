import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sync import run_sync_all


def _tz():
    name = os.environ.get("REPORT_TZ") or os.environ.get("TZ") or "Europe/Budapest"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def _truthy(v, default=True):
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def next_report_at(tz, hour, minute):
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def wait_until(target, tz):
    while True:
        remaining = (target - datetime.now(tz)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 30))


def teams_report_loop():
    hour = int(os.environ.get("TEAMS_REPORT_HOUR", "9"))
    minute = int(os.environ.get("TEAMS_REPORT_MINUTE", "0"))
    tz = _tz()
    while True:
        target = next_report_at(tz, hour, minute)
        print(f"下次 Teams 报告：{target.strftime('%Y-%m-%d %H:%M %Z')}", flush=True)
        wait_until(target, tz)
        try:
            print("======== 定时任务：发送昨日入库 Teams 报告 ========", flush=True)
            from send import run
            print(run(), flush=True)
            print("======== 定时任务：Teams 报告结束 ========", flush=True)
        except Exception as e:
            print("teams report failed:", repr(e), flush=True)


interval = int(os.environ.get("SYNC_INTERVAL_MINUTES", "60")) * 60
if _truthy(os.environ.get("TEAMS_REPORT_ENABLED"), default=True):
    threading.Thread(target=teams_report_loop, name="teams-report", daemon=True).start()

while True:
    try:
        print("======== 定时任务：开始全量同步 ========", flush=True)
        print(run_sync_all(), flush=True)
        print("======== 定时任务：本轮结束 ========", flush=True)
    except Exception as e:
        print("sync failed:", repr(e), flush=True)
    print(f"下次同步将在 {interval // 60} 分钟后", flush=True)
    time.sleep(interval)
