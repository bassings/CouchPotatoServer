# Library Migration: Vendored → PyPI

## Overview

CouchPotatoServer historically vendored all dependencies in `libs/`. This document
tracks the migration to standard PyPI packages managed via `requirements.txt`.

## API Differences

### APScheduler (2.1.2 → 3.11.2)

The most significant API change. The vendored v2.x used:

```python
from apscheduler.scheduler import Scheduler
sched = Scheduler()
sched.add_cron_job(func, day=day, hour=hour, minute=minute)
sched.add_interval_job(func, hours=h, minutes=m, seconds=s)
sched.unschedule_job(job)
sched.shutdown(wait=False)
```

APScheduler v3.x uses:

```python
from apscheduler.schedulers.background import BackgroundScheduler
sched = BackgroundScheduler(misfire_grace_time=60)
sched.add_job(func, 'cron', day=day, hour=hour, minute=minute)
sched.add_job(func, 'interval', hours=h, minutes=m, seconds=s)
sched.remove_job(job_id)
sched.shutdown(wait=False)
```

**Migration approach:** Created a compatibility shim `libs/apscheduler_compat.py` that
wraps APScheduler v3 with a v2-like interface, then updated `scheduler.py` to use it.

### guessit (0.x → 3.8.0)

Old API:
```python
from guessit import guess_movie_info
result = guess_movie_info(filename)
```

New API:
```python
from guessit import guessit
result = guessit(filename, {'type': 'movie'})
```

Return keys are the same (`title`, `year`, etc.).

### requests

No significant API changes. The vendored version used `requests.packages.urllib3`
for internal access; modern requests still supports this but it's deprecated.
Updated to import directly from `urllib3` where needed.

### tornado

Updated from vendored ~4.x to 6.x. The core APIs used (HTTPServer, Application,
RequestHandler, IOLoop, StaticFileHandler) remain compatible.

### Other Libraries

- **beautifulsoup4/bs4**: No API changes
- **html5lib**: No API changes
- **chardet**: No API changes (`from chardet import detect` still works)
- **python-dateutil**: No API changes (`from dateutil.parser import parse`)
- **rsa**: No API changes
- **oauthlib**: No API changes
- **enzyme**: No API changes
- **certifi**: No API changes

## Removed Vendored Libraries

| Library | Reason |
|---------|--------|
| `libs/requests/` | Replaced by PyPI `requests` |
| `libs/tornado/` | Replaced by PyPI `tornado` |
| `libs/certifi/` | Replaced by PyPI `certifi` |
| `libs/bs4/` | Replaced by PyPI `beautifulsoup4` |
| `libs/html5lib/` | Replaced by PyPI `html5lib` |
| `libs/guessit/` | Replaced by PyPI `guessit` |
| `libs/chardet/` | Replaced by PyPI `chardet` |
| `libs/apscheduler/` | Replaced by PyPI `APScheduler` |
| `libs/dateutil/` | Replaced by PyPI `python-dateutil` |
| `libs/rsa/` | Replaced by PyPI `rsa` |
| `libs/oauthlib/` | Replaced by PyPI `oauthlib` |
| `libs/enzyme/` | Replaced by PyPI `enzyme` |
| `libs/pyasn1/` | Replaced by PyPI `pyasn1` |
| `libs/pyutil/` | Removed — unused |
| `libs/suds/` | Removed — unused |
| `libs/six.py` | Replaced by PyPI `six` |

## Libraries Kept Vendored

| Library | Reason |
|---------|--------|
| `libs/CodernityDB/` | Custom fork, no PyPI equivalent |
| `libs/subliminal/` | Heavily patched custom version |
| `libs/xmpp/` | Legacy XMPP lib, no maintained replacement |
| `libs/oauth2/` | Used by Twitter notifications, legacy |
| `libs/gntp/` | Growl notifications |
| `libs/bencode/` | Simple bencode implementation |
| `libs/caper/` | Custom media parsing |
| `libs/axl/` | Custom XML library |
| Various others | App-specific or no PyPI equivalent |
