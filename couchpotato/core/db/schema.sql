-- CouchPotatoServer SQLite Schema
-- Migrated from CodernityDB document store
-- All documents stored in a single 'documents' table with JSON data
-- Plus indexed columns for common query patterns

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Core document store: mirrors CodernityDB's document model
-- Every CodernityDB document becomes a row here
CREATE TABLE IF NOT EXISTS documents (
    _id TEXT PRIMARY KEY,
    _rev TEXT NOT NULL,
    _t TEXT NOT NULL,  -- document type: media, release, quality, profile, category, notification, property
    data JSON NOT NULL,  -- full document as JSON (includes all fields)
    created_at REAL,
    updated_at REAL
);

-- Type index: filter by document type
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(_t);

-- === Media indexes ===
-- Status lookup (MediaStatusIndex)
CREATE INDEX IF NOT EXISTS idx_media_status ON documents(_t, json_extract(data, '$.status'))
    WHERE _t = 'media';

-- Type lookup (MediaTypeIndex) - movie, show, etc.
CREATE INDEX IF NOT EXISTS idx_media_type ON documents(_t, json_extract(data, '$.type'))
    WHERE _t = 'media';

-- Title sorting (TitleIndex)
CREATE INDEX IF NOT EXISTS idx_media_title ON documents(json_extract(data, '$.title'))
    WHERE _t = 'media';

-- Parent-child relationships (MediaChildrenIndex)
CREATE INDEX IF NOT EXISTS idx_media_parent ON documents(json_extract(data, '$.parent_id'))
    WHERE _t = 'media' AND json_extract(data, '$.parent_id') IS NOT NULL;

-- Category lookup (CategoryMediaIndex)
CREATE INDEX IF NOT EXISTS idx_media_category ON documents(json_extract(data, '$.category_id'))
    WHERE _t = 'media' AND json_extract(data, '$.category_id') IS NOT NULL;

-- === Release indexes ===
-- By media_id (ReleaseIndex)
CREATE INDEX IF NOT EXISTS idx_release_media ON documents(json_extract(data, '$.media_id'))
    WHERE _t = 'release';

-- By status (ReleaseStatusIndex)
CREATE INDEX IF NOT EXISTS idx_release_status ON documents(json_extract(data, '$.status'))
    WHERE _t = 'release';

-- By identifier (ReleaseIDIndex)
CREATE INDEX IF NOT EXISTS idx_release_identifier ON documents(json_extract(data, '$.identifier'))
    WHERE _t = 'release';

-- === Category indexes ===
CREATE INDEX IF NOT EXISTS idx_category_order ON documents(json_extract(data, '$.order'))
    WHERE _t = 'category';

-- === Profile indexes ===
CREATE INDEX IF NOT EXISTS idx_profile_order ON documents(json_extract(data, '$.order'))
    WHERE _t = 'profile';

-- === Quality indexes ===
CREATE INDEX IF NOT EXISTS idx_quality_identifier ON documents(json_extract(data, '$.identifier'))
    WHERE _t = 'quality';

-- === Notification indexes ===
CREATE INDEX IF NOT EXISTS idx_notification_time ON documents(json_extract(data, '$.time'))
    WHERE _t = 'notification';

-- Unread notifications
CREATE INDEX IF NOT EXISTS idx_notification_unread ON documents(json_extract(data, '$.time'))
    WHERE _t = 'notification' AND json_extract(data, '$.read') != 1;

-- === Property indexes ===
CREATE INDEX IF NOT EXISTS idx_property_identifier ON documents(json_extract(data, '$.identifier'))
    WHERE _t = 'property';

-- === Media identifiers lookup table ===
-- Denormalized for fast identifier lookups (MediaIndex is a MultiTreeBasedIndex)
CREATE TABLE IF NOT EXISTS media_identifiers (
    media_id TEXT NOT NULL REFERENCES documents(_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    identifier TEXT NOT NULL,
    PRIMARY KEY (media_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_media_identifiers_lookup ON media_identifiers(provider, identifier);

-- === Media tags lookup table ===
-- Denormalized for fast tag lookups (MediaTagIndex is a MultiTreeBasedIndex)
CREATE TABLE IF NOT EXISTS media_tags (
    media_id TEXT NOT NULL REFERENCES documents(_id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (media_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_media_tags_tag ON media_tags(tag);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, strftime('%s', 'now'));
