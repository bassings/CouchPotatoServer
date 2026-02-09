# Notification Services Status

## Active Services

| Service | Status | Notes |
|---------|--------|-------|
| Discord | ✅ Active | Webhook-based notifications |
| Email | ✅ Active | SMTP email notifications |
| Emby | ✅ Active | Library update notifications |
| Kodi (XBMC) | ✅ Active | Library update + on-screen notifications |
| Plex | ✅ Active | Library refresh + client notifications |
| Pushbullet | ✅ Active | Push notifications |
| Pushover | ✅ Active | Push notifications |
| Slack | ✅ Active | Webhook-based notifications |
| Telegram | ✅ Active | Bot-based notifications |
| Trakt | ✅ Active | Scrobbling/collection sync |
| Webhook | ✅ Active | Generic webhook for custom integrations |
| Script | ✅ Active | Run custom scripts on events |

## Legacy/Deprecated Services

| Service | Status | Notes |
|---------|--------|-------|
| Android Push Notification | ❌ Dead | Service shut down |
| Boxcar2 | ❌ Dead | Service shut down |
| Growl | ⚠️ Deprecated | macOS-only, largely abandoned |
| Homey | ⚠️ Legacy | Smart home platform |
| Join | ⚠️ Legacy | Joao's cross-device tool |
| NMJ | ⚠️ Legacy | Networked Media Jukebox (Popcorn Hour) |
| NotifyMyAndroid | ❌ Dead | Service shut down |
| Prowl | ⚠️ Deprecated | iOS-only, rarely updated |
| Pushalot | ❌ Dead | Service shut down |
| SynoIndex | ⚠️ Legacy | Synology-specific indexing |
| Toasty | ❌ Dead | Service shut down |
| Twitter | ⚠️ Deprecated | API changes, OAuth complexity |
| XMPP | ⚠️ Deprecated | Jabber protocol, rarely used |

## Python 3 Changes

The following fixes were applied to notification services:

- `from urlparse import ...` → `from urllib.parse import ...`
- `import urllib, urllib2` → `import urllib.parse, urllib.request, urllib.error`
- `urllib.urlencode()` → `urllib.parse.urlencode()`
- `base64.encodestring()` → `base64.b64encode()` with proper bytes handling
- String data encoded to bytes for `urllib.request.Request`
- `urllib.request.Request(url, data="")` → `data=b""`

## Configuration

All notification services are configured via the web UI under Settings → Notifications.
Each service supports:

- **Enabled/Disabled** toggle
- **Service-specific** settings (API keys, webhooks, hosts)
- **On Snatch** — notify when a release is grabbed
- **On Download** — notify when a download completes
