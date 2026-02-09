# CouchPotatoServer Database Schema

## Overview

CouchPotatoServer uses a document-oriented storage model. The original CodernityDB backend stored schemaless JSON documents with custom indexes. The SQLite backend preserves this model using a single `documents` table with JSON data columns, plus SQLite indexes for query performance.

## Architecture

```
┌─────────────────────────────────────────────┐
│              DatabaseInterface               │
│  (couchpotato/core/db/interface.py)         │
├──────────────────┬──────────────────────────┤
│ CodernityDBAdapter│    SQLiteAdapter         │
│ (legacy)          │    (new)                 │
└──────────────────┴──────────────────────────┘
```

## Document Types

### `media` — Movies/Shows
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"media"` |
| `status` | string | `active`, `done`, `deleted` |
| `title` | string | Display title |
| `type` | string | `movie`, `show` |
| `profile_id` | string | Reference to profile document |
| `category_id` | string | Reference to category document |
| `identifiers` | object | `{"imdb": "tt...", "tmdb": 123}` |
| `info` | object | TMDb metadata, images, cast, etc. |
| `tags` | array | User-defined tags |
| `parent_id` | string | Parent media ID (for episodes/seasons) |

### `release` — Download Releases
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"release"` |
| `media_id` | string | Reference to parent media document |
| `identifier` | string | Release identifier string |
| `quality` | string | Quality level (e.g. `720p`) |
| `status` | string | `available`, `snatched`, `done`, etc. |
| `is_3d` | boolean | 3D release flag |
| `last_edit` | number | Unix timestamp |
| `files` | object | `{"movie": [...], "subtitle": [...]}` |
| `info` | object | Release metadata |
| `download_info` | object | `{"id": "...", "downloader": "..."}` |

### `quality` — Quality Definitions
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"quality"` |
| `identifier` | string | e.g. `2160p`, `1080p`, `720p` |
| `order` | integer | Sort order |
| `size_min` | integer | Minimum size in MB |
| `size_max` | integer | Maximum size in MB |

### `profile` — Quality Profiles
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"profile"` |
| `label` | string | Display name |
| `order` | integer | Sort order |
| `core` | boolean | Built-in profile |
| `hide` | boolean | Hidden from UI |
| `qualities` | array | List of quality identifiers |
| `wait_for` | array | Wait times per quality |
| `finish` | array | Finish flags per quality |
| `stop_after` | integer | Stop after N matches |
| `minimum_score` | integer | Minimum score threshold |
| `3d` | boolean | 3D preference |

### `category` — Media Categories
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"category"` |
| `label` | string | Display name |
| `order` | integer | Sort order |
| `required` | string | Required words |
| `preferred` | string | Preferred words |
| `ignored` | string | Ignored words |
| `destination` | string | Download destination path |

### `notification` — Notifications
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"notification"` |
| `message` | string | Notification text |
| `time` | integer | Unix timestamp |
| `read` | boolean | Read status |

### `property` — Key-Value Settings
| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"property"` |
| `identifier` | string | Setting key |
| `value` | string | Setting value |

## SQLite Tables

### `documents`
Single table for all document types. The `data` column contains the full JSON document. Indexed columns extracted via `json_extract()` for query performance.

### `media_identifiers`
Denormalized lookup table for media identifiers (IMDb, TMDb, etc.). Populated from `media.identifiers` field.

### `media_tags`
Denormalized lookup table for media tags. Populated from `media.tags` field.

### `schema_version`
Tracks applied schema migrations.

## Index Mapping

| CodernityDB Index | SQLite Equivalent |
|-------------------|-------------------|
| `MediaIndex` (multi-key) | `media_identifiers` table |
| `MediaStatusIndex` | `idx_media_status` |
| `MediaTypeIndex` | `idx_media_type` |
| `TitleIndex` | `idx_media_title` |
| `StartsWithIndex` | Computed at query time |
| `TitleSearchIndex` | `LIKE` query on title |
| `MediaChildrenIndex` | `idx_media_parent` |
| `MediaTagIndex` | `media_tags` table |
| `CategoryMediaIndex` | `idx_media_category` |
| `ReleaseIndex` | `idx_release_media` |
| `ReleaseStatusIndex` | `idx_release_status` |
| `ReleaseIDIndex` | `idx_release_identifier` |
| `ReleaseDownloadIndex` | Computed at query time |
| `CategoryIndex` | `idx_category_order` |
| `ProfileIndex` | `idx_profile_order` |
| `QualityIndex` | `idx_quality_identifier` |
| `NotificationIndex` | `idx_notification_time` |
| `NotificationUnreadIndex` | `idx_notification_unread` |
| `PropertyIndex` | `idx_property_identifier` |

## Migration

Use the migration tool to convert from CodernityDB:

```bash
python -m couchpotato.core.db.migrate --source /path/to/database --dest /path/to/new.db
python -m couchpotato.core.db.migrate --source /path/to/database --dest /path/to/new.db --verify
```
