# Test Database Fixtures

This directory contains sanitized sample data extracted from a real CouchPotatoServer CodernityDB database.

## Source
- Extracted from `config_backup.zip` containing a production database
- All personal data (API keys, paths, usernames) has been sanitized
- Document structure and relationships preserved

## Files
- `../sample_data.json` - Complete sanitized document examples for all 6 document types

## Database Format
The original CodernityDB database uses:
- **Hash index** (`id_buck`/`id_stor`) for primary document storage
- **Tree indexes** for secondary lookups (by status, type, title, etc.)
- **Marshal serialization** for both bucket metadata and document storage
- **Python 2 marshal format** for media documents (requires custom decoder)

## Record Counts (from real database)
| Type | Count | Description |
|------|-------|-------------|
| media | 849 | Movie records with metadata |
| release | 905 | Download releases linked to media |
| property | 1,101 | Key-value settings/state |
| quality | 12 | Quality definitions (720p, 1080p, etc.) |
| profile | 17 | User preference profiles |
| notification | 8 | User notifications |
| **Total** | **2,892** | |
