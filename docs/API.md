# CouchPotato API Reference

CouchPotato uses a FastAPI-based API. All endpoints are prefixed with the configured API base
(default: `/api/<api_key>/`).

## Interactive Documentation

When running, FastAPI provides automatic OpenAPI documentation:
- **Swagger UI**: `http://localhost:5050/docs`
- **ReDoc**: `http://localhost:5050/redoc`
- **OpenAPI JSON**: `http://localhost:5050/openapi.json`

## Core Endpoints

### Application

| Endpoint | Description |
|----------|-------------|
| `app.available` | Check if the app is running |
| `app.version` | Get application version |
| `app.restart` | Restart the application |
| `app.shutdown` | Shut down the application |

### Movies

| Endpoint | Description |
|----------|-------------|
| `movie.add` | Add a movie to the wanted list |
| `movie.edit` | Edit movie details |
| `media.list` | List all movies (with filters) |
| `media.get` | Get a specific movie |
| `media.delete` | Delete a movie |
| `media.refresh` | Refresh movie metadata |
| `media.available_chars` | Get available first characters for filtering |

### Search

| Endpoint | Description |
|----------|-------------|
| `search` | Search for movies by title |
| `movie.searcher.full_search` | Trigger a full search for all wanted movies |
| `movie.searcher.try_next` | Try next release for a movie |
| `movie.searcher.progress` | Get current search progress |
| `searcher.full_search` | Alternative full search endpoint |
| `searcher.progress` | Alternative search progress endpoint |

### Releases

| Endpoint | Description |
|----------|-------------|
| `release.manual_download` | Manually download a specific release |
| `release.delete` | Delete a release |
| `release.ignore` | Ignore/unignore a release |

### Quality Profiles

| Endpoint | Description |
|----------|-------------|
| `quality.list` | List all quality definitions |
| `quality.size.save` | Save quality size settings |
| `profile.list` | List all profiles |
| `profile.save` | Save a profile |
| `profile.save_order` | Save profile display order |
| `profile.delete` | Delete a profile |

### Categories

| Endpoint | Description |
|----------|-------------|
| `category.list` | List all categories |
| `category.save` | Save a category |
| `category.save_order` | Save category display order |
| `category.delete` | Delete a category |

### Notifications

| Endpoint | Description |
|----------|-------------|
| `notification.list` | Get recent notifications |
| `notification.listener` | Long-poll for new notifications |
| `notification.markread` | Mark notifications as read |

### Dashboard

| Endpoint | Description |
|----------|-------------|
| `dashboard.soon` | Get upcoming/recent movies |
| `charts.view` | View movie charts |
| `charts.ignore` | Ignore a chart entry |
| `suggestion.view` | Get movie suggestions |
| `suggestion.ignore` | Ignore a suggestion |

### Library

| Endpoint | Description |
|----------|-------------|
| `library.query` | Query the library |
| `library.related` | Get related movies |
| `library.tree` | Get library tree structure |

### Automation

| Endpoint | Description |
|----------|-------------|
| `automation.add_movies` | Add movies from automation sources |

### Database

| Endpoint | Description |
|----------|-------------|
| `database.compact` | Compact the database |
| `database.list_documents` | List database documents |
| `database.document.update` | Update a document |
| `database.document.delete` | Delete a document |
| `database.reindex` | Reindex the database |

### Library Management

| Endpoint | Description |
|----------|-------------|
| `manage.update` | Trigger library scan |
| `manage.progress` | Get scan progress |

### Settings

| Endpoint | Description |
|----------|-------------|
| `settings` | Get all settings |
| `settings.save` | Save settings |

### Downloaders

| Endpoint | Description |
|----------|-------------|
| `download.<name>.test` | Test downloader connection |

### Logging

| Endpoint | Description |
|----------|-------------|
| `logging.get` | Get log entries |
| `logging.partial` | Get partial log |
| `logging.log` | Submit a log entry |
| `logging.clear` | Clear logs |

### Updater

| Endpoint | Description |
|----------|-------------|
| `updater.info` | Get update information |
| `updater.check` | Check for updates |
| `updater.update` | Trigger update |

### File Browser

| Endpoint | Description |
|----------|-------------|
| `directory.list` | List directory contents (for UI file browser) |
| `file.cache/(.*)` | Serve cached files |

### Userscripts

| Endpoint | Description |
|----------|-------------|
| `userscript` | Userscript iframe |
| `userscript.add_via_url` | Add movie via URL |
| `userscript.includes` | Get userscript includes |
| `userscript.bookmark` | Bookmark functionality |
| `userscript.get/<provider>/<script>` | Get a specific userscript |

## Authentication

API calls require the API key in the URL path: `/api/<api_key>/<endpoint>`.
The API key is generated on first run and stored in settings.

## Response Format

Most endpoints return JSON with the structure:
```json
{
  "success": true,
  ...
}
```
