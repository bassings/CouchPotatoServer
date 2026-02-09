# CouchPotatoServer Data Model

## Overview

CouchPotatoServer uses CodernityDB, an embedded NoSQL document database. All documents are stored in a single collection with a `_t` (type) field for discrimination. Documents are serialized using Python's `marshal` format.

## Document Types

### media
Movies tracked by CouchPotatoServer.

| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"media"` |
| `status` | string | `"active"` (wanted), `"done"` (downloaded), `"deleted"` |
| `title` | string | Primary display title |
| `type` | string | Media type, always `"movie"` currently |
| `profile_id` | string\|null | Reference to quality profile document ID |
| `category_id` | string\|null | Reference to category document ID |
| `identifiers` | dict | `{"imdb": "ttXXXXXXX"}` and optionally `{"tmdb": 12345}` |
| `info` | dict | Rich metadata from TMDb (see below) |
| `files` | dict | `{"image_poster": ["/path/to/poster.jpg"]}` |
| `tags` | list | User-assigned tags |
| `last_edit` | int | Unix timestamp of last modification |

#### info sub-document
| Field | Type | Description |
|-------|------|-------------|
| `tmdb_id` | int | TMDb identifier |
| `imdb` | string | IMDb identifier (e.g., `"tt13320622"`) |
| `year` | int | Release year |
| `released` | string | Release date `"YYYY-MM-DD"` |
| `plot` | string | Synopsis |
| `genres` | list[string] | Genre names |
| `titles` | list[string] | All known titles (international) |
| `original_title` | string | Original language title |
| `runtime` | int | Runtime in minutes |
| `mpaa` | string\|null | MPAA rating |
| `tagline` | string | Marketing tagline |
| `actors` | list | Actor names |
| `actor_roles` | dict | Actor → role mapping |
| `via_tmdb` | bool | Whether info came from TMDb |
| `images` | dict | Image URLs by type (poster, backdrop, disc_art, etc.) |

### release
Download releases associated with a media item.

| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"release"` |
| `status` | string | `"done"`, `"snatched"`, `"available"`, `"ignored"`, `"deleted"` |
| `media_id` | string | Reference to parent media document ID |
| `identifier` | string | Release identifier, typically `"ttXXXXXXX.codec.quality"` |
| `quality` | string | Quality identifier (e.g., `"720p"`, `"1080p"`) |
| `is_3d` | bool | Whether release is 3D |
| `last_edit` | int | Unix timestamp |
| `files` | dict | File paths by type: `movie`, `subtitle`, `nfo`, `leftover`, `subtitle_extra` |
| `info` | dict | Release metadata (name, size, provider info) |
| `download_info` | dict\|null | `{"id": "...", "downloader": "sabnzbd", "status_support": true}` |

### quality
Quality definitions with size ranges.

| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"quality"` |
| `identifier` | string | Quality name: `"2160p"`, `"1080p"`, `"720p"`, `"bd50"`, etc. |
| `order` | int | Display/priority order |
| `size_min` | int | Minimum file size in MB |
| `size_max` | int | Maximum file size in MB |

### profile
Quality preference profiles defining which qualities to accept.

| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"profile"` |
| `label` | string | Profile name (e.g., `"Best"`, `"High"`, `"Mid"`) |
| `order` | int | Display order |
| `core` | bool | Whether this is a built-in profile |
| `hide` | bool | Whether to hide in UI |
| `qualities` | list[string] | Quality identifiers in preference order |
| `wait_for` | list[int] | Days to wait for each quality before falling back |
| `finish` | list[bool] | Whether each quality is a "finish" quality |
| `stop_after` | int | Stop searching after N days |
| `minimum_score` | int | Minimum search result score |
| `3d` | bool | Whether to prefer 3D releases |

### notification
User notifications for events.

| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"notification"` |
| `message` | string | Human-readable notification text |
| `time` | int | Unix timestamp |
| `read` | bool | Whether notification has been read |

### property
Key-value store for application state and settings.

| Field | Type | Description |
|-------|------|-------------|
| `_t` | string | Always `"property"` |
| `identifier` | string | Property key (e.g., `"manage.last_update"`) |
| `value` | string | Property value (always stored as string) |

## Indexes

CodernityDB uses 20 index files for efficient querying:

| # | Name | Type | Key Format | Description |
|---|------|------|-----------|-------------|
| 00 | `id` | UniqueHashIndex | 32s+8s | Primary document storage |
| 01 | `release` | TreeBasedIndex | 32s | Releases by `media_id` |
| 02 | `notification` | TreeBasedIndex | I (uint) | Notifications by `time` |
| 03 | `quality` | HashIndex | 32s (md5) | Qualities by `identifier` |
| 04 | `profile` | TreeBasedIndex | i (int) | Profiles by `order` |
| 05 | `category` | TreeBasedIndex | i (int) | Categories by `order` |
| 06 | `property` | HashIndex | 32s (md5) | Properties by `identifier` |
| 07 | `media_children` | TreeBasedIndex | 32s | Media by `parent_id` |
| 08 | `category_media` | TreeBasedIndex | 32s | Media by `category_id` |
| 09 | `notification_unread` | TreeBasedIndex | I (uint) | Unread notifications by `time` |
| 10 | `media_search_title` | MultiTreeBasedIndex | 32s | Media full-text search on title |
| 11 | `release_download` | HashIndex | 32s (md5) | Releases by download info |
| 12 | `media_tag` | MultiTreeBasedIndex | 32s (md5) | Media by tags |
| 13 | `release_identifier` | HashIndex | 32s (md5) | Releases by `identifier` |
| 14 | `media_startswith` | TreeBasedIndex | 1s | Media by first letter of title |
| 15 | `release_status` | TreeBasedIndex | 32s (md5) | Releases by `status` |
| 16 | `media` | MultiTreeBasedIndex | 32s (md5) | Media by identifiers (imdb/tmdb) |
| 17 | `media_by_type` | TreeBasedIndex | 32s (md5) | Media by `type` |
| 18 | `media_status` | TreeBasedIndex | 32s (md5) | Media by `status` |
| 19 | `media_title` | TreeBasedIndex | 32s | Media by simplified title |

## Relationships

```
profile ←── media ──→ category
                │
                ├──→ release (via media_id)
                │       └──→ quality (via quality identifier)
                │
                └──→ notification (implicit, via events)

property (standalone key-value store)
```

## Storage Format

- **Bucket files** (`*_buck`): Hash/tree index structures with marshal-encoded headers
  - First 500 bytes: marshal-encoded props dict (name, format, hash_lim, version)
  - Remaining: bucket pointers and entry chains
- **Storage files** (`*_stor`): marshal-encoded document data
  - First 100 bytes: version header
  - Remaining: concatenated marshal-encoded documents at offsets referenced by bucket entries

### ID Index Entry Format
```
struct entry {
    char doc_id[32];    // Document ID (hex string)
    char rev[8];        // Revision
    uint32 start;       // Offset into _stor file
    uint32 size;        // Size of marshaled document
    char status;        // 'o' = active, 'd' = deleted
    uint32 next;        // Next entry in chain (0 = end)
};  // Total: 53 bytes
```

## Python 2/3 Compatibility Note

Documents written by the Python 2 version of CouchPotatoServer use Python 2 marshal encoding which differs from Python 3:
- Type code `0x74` = TYPE_INTERNED (interned string, added to reference table)
- Type code `0x73` = TYPE_STRING (regular string)
- Type code `0x52` = TYPE_STRINGREF (reference to previously interned string)
- Type code `0x75` = TYPE_UNICODE

Media documents in particular require a custom Python 2 marshal decoder when read from Python 3, as the standard `marshal.loads()` fails on interned string references.
