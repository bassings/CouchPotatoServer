# Providers Status Matrix

## Info Providers

| Provider | Status | Notes |
|----------|--------|-------|
| TheMovieDB | ✅ Active | Primary metadata source |
| OMDb API | ✅ Active | Requires API key |
| FanartTV | ✅ Active | Artwork provider |
| CouchPotato API | ⚠️ Deprecated | Original CP API, likely offline |

## Torrent Providers

| Provider | Status | Notes |
|----------|--------|-------|
| AlphaRatio | ⚠️ Unknown | Private tracker |
| AwesomeHD | ❌ Dead | Shut down |
| BitHDTV | ⚠️ Unknown | Private tracker |
| BitSoup | ❌ Dead | Shut down ~2016 |
| HD4Free | ❌ Dead | Shut down |
| HDBits | ✅ Active | Private tracker |
| ILoveTorrents | ❌ Dead | Shut down |
| IPTorrents | ✅ Active | Private tracker |
| KickAssTorrents | ❌ Dead | Original domain shut down |
| MagnetDL | ❌ Dead | Shut down |
| MoreThanTV | ❌ Dead | Shut down 2023 |
| PassThePopcorn | ✅ Active | Private tracker, invite-only |
| RARBG | ❌ Dead | Shut down May 2023 |
| SceneAccess | ❌ Dead | Shut down ~2019 |
| SceneTime | ⚠️ Unknown | Private tracker |
| TorrentBytes | ⚠️ Unknown | Private tracker |
| TorrentDay | ✅ Active | Private tracker |
| TorrentLeech | ✅ Active | Private tracker |
| TorrentPotato | ✅ Active | Generic API (Jackett/Prowlarr compatible) |
| TorrentShack | ❌ Dead | Shut down |
| Torrentz | ❌ Dead | Shut down (torrentz2 variants exist) |
| YTS | ✅ Active | Public, movie-focused |

## NZB Providers

| Provider | Status | Notes |
|----------|--------|-------|
| Newznab | ✅ Active | Generic API (NZBGeek, NZBPlanet, etc.) |
| Binsearch | ⚠️ Deprecated | Raw NZB search, limited |
| NZBClub | ❌ Dead | Shut down |
| OmgWtfNzbs | ❌ Dead | Shut down |

## Automation Providers

| Provider | Status | Notes |
|----------|--------|-------|
| Blu-ray.com | ✅ Active | Release date tracking |
| CrowdAI | ❌ Dead | Service shut down |
| Flixster | ❌ Dead | Merged into Fandango |
| Goodfilms | ❌ Dead | Service shut down |
| Hummingbird | ❌ Dead | Became Kitsu |
| IMDb | ✅ Active | Watchlist automation |
| iTunes | ⚠️ Deprecated | API changes |
| Letterboxd | ✅ Active | Watchlist automation |
| Popular Movies | ✅ Active | TMDb popular list |
| Trakt | ✅ Active | Watchlist automation |
| YifyPopular | ❌ Dead | Depends on YTS availability |

## Trailer Providers

| Provider | Status | Notes |
|----------|--------|-------|
| HD-Trailers.net | ⚠️ Deprecated | Scraping-based, fragile |

## Userscript Providers

These are browser userscripts for adding movies from external sites. They are client-side
JavaScript and don't require Python 3 changes.

| Provider | Status |
|----------|--------|
| IMDb | ✅ Active |
| TMDb | ✅ Active |
| Trakt | ✅ Active |
| Letterboxd | ✅ Active |
| Rotten Tomatoes | ✅ Active |
| Reddit | ✅ Active |
| Criticker | ⚠️ Unknown |
| Allocine | ⚠️ Unknown |
| Filmweb | ⚠️ Unknown |
| FlickChart | ⚠️ Unknown |
| MovieMeter | ⚠️ Unknown |
| Apple Trailers | ❌ Dead |
| MoviesIO | ❌ Dead |
| Filmcentrum | ⚠️ Unknown |
| Filmstarts | ⚠️ Unknown |
| YouTheather | ⚠️ Unknown |

## Python 3 Compatibility

All provider modules have been audited and updated for Python 3 compatibility:
- `urlparse` → `urllib.parse`
- String/bytes handling updated
- Regex patterns use raw strings
- Dead providers are left as-is (no functional changes needed for inactive code)
