import time
from datetime import datetime, timedelta

from apscheduler.scheduler import Scheduler


def test_scheduler_runs_one_job():
    calls = []

    def task(x):
        calls.append(x)

    sched = Scheduler({'apscheduler.misfire_grace_time': 5, 'apscheduler.daemonic': True})
    run_at = datetime.now() + timedelta(milliseconds=100)
    sched.add_date_job(task, run_at, args=["ok"])
    sched.start()

    # Wait up to 2 seconds for the job to fire
    for _ in range(40):
        if calls:
            break
        time.sleep(0.05)

    try:
        assert calls == ["ok"]
    finally:
        sched.shutdown(wait=True)

