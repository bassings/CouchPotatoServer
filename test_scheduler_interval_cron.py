import time
from datetime import datetime, timedelta

from apscheduler.scheduler import Scheduler


def test_scheduler_interval_runs_multiple():
    calls = []

    def task():
        calls.append(datetime.now())

    sched = Scheduler({'apscheduler.daemonic': True})
    sched.add_interval_job(task, seconds=0.1)
    sched.start()

    try:
        time.sleep(0.35)
        assert len(calls) >= 2
    finally:
        sched.shutdown(wait=True)


def test_scheduler_cron_next_time():
    calls = []

    def task():
        calls.append(True)

    now = datetime.now()
    next_second = (now + timedelta(seconds=1)).second

    sched = Scheduler({'apscheduler.daemonic': True})
    sched.add_cron_job(task, second=next_second)
    sched.start()
    try:
        time.sleep(1.5)
        assert calls, "Cron job should have fired at next second"
    finally:
        sched.shutdown(wait=True)

