import os
import time
from sync import run_sync_all

interval = int(os.environ.get("SYNC_INTERVAL_MINUTES", "60")) * 60
while True:
    try:
        print("start sync", flush=True)
        print(run_sync_all(), flush=True)
    except Exception as e:
        print("sync failed:", repr(e), flush=True)
    time.sleep(interval)
