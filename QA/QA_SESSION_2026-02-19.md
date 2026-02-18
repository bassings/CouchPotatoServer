# QA Session - 2026-02-19

**Version:** v3.1.0 (dev build from master)
**Tester:** Eggbert (AI)
**Environment:** Local Docker (docker-compose.dev.yml, port 5051)

---

## Pre-QA Checks

- [x] Local tests pass (`test_startup_local.py`, `test_sqlite_adapter.py`)
- [x] Lint passes (`ruff check .`)
- [x] Dev container builds successfully
- [x] Container starts and logs show startup sequence
- [x] UI accessible at http://localhost:5051

---

## Issues Found

### DEF-010: Quality fill fails on fresh database (CRITICAL)
**Severity:** High
**Component:** Quality plugin
**Steps to reproduce:**
1. Start fresh container with empty database
2. Check container logs

**Expected:** Quality profiles created successfully
**Actual:** KeyError when trying to get non-existent quality

**Error:**
```
KeyError: "No document found in index 'quality' for key: 2160p"
```

**Root cause:** `db.get()` raises KeyError when document doesn't exist, but `fill()` method in quality plugin expects it to return None or handle missing gracefully.

**File:** `couchpotato/core/plugins/quality/main.py:194`

---

## Test Execution

### 1. Navigation & Core Pages
| Test | Status | Notes |
|------|--------|-------|
| Home/Wanted page loads | ⏳ | |
| Available page loads | ⏳ | |
| Suggestions page loads | ⏳ | |
| Add Movie page loads | ⏳ | |
| Settings page loads | ⏳ | |
| Movie detail page loads | ⏳ | |

### 2. Core User Flows
| Test | Status | Notes |
|------|--------|-------|
| Search for movie | ⏳ | |
| Add movie to wanted | ⏳ | |
| View movie details | ⏳ | |
| Filter wanted list | ⏳ | |
| Delete movie | ⏳ | |

### 3. Settings
| Test | Status | Notes |
|------|--------|-------|
| Settings tabs load | ⏳ | |
| Test searcher connection | ⏳ | |
| Test downloader connection | ⏳ | |
| Save settings persists | ⏳ | |

### 4. New Features (v3.1.0)
| Test | Status | Notes |
|------|--------|-------|
| SQLite database works | ⏳ | |
| Fresh install creates SQLite | ⏳ | |

---

## Notes

- Container running on port 5051
- Fresh database (no migration from CodernityDB)
- Quality fill error needs TDD fix before continuing full QA
