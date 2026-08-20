import os
import time
from sync import run_sync_all

interval = int(os.environ.get("SYNC_INTERVAL_MINUTES", "60")) * 60
while True:
    try:
        print("======== 定时任务：开始全量同步 ========", flush=True)
        print(run_sync_all(), flush=True)
        print("======== 定时任务：本轮结束 ========", flush=True)
    except Exception as e:
        print("sync failed:", repr(e), flush=True)
    print(f"下次同步将在 {interval // 60} 分钟后", flush=True)
    time.sleep(interval)
