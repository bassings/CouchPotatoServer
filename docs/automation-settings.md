# CouchPotato Automation & Suggestions Settings Guide

This document describes the automation plugins in CouchPotato that can automatically add movies to your wanted list, and the suggestion system that helps you discover new movies.

## Automation System Overview

The automation system runs on a configurable interval (default: 12 hours) and checks various sources for movies to add. All automation sources respect the global filters configured in **Automation → Auto-Add Filters**.

### Global Auto-Add Filters

These filters apply to ALL automation sources:

| Setting | Default | Description |
|---------|---------|-------------|
| **Minimum Year** | 2011 | Only add movies released in this year or later |
| **Minimum Votes** | 1000 | Only add movies with this many IMDB votes or more |
| **Minimum Rating** | 7.0 | Only add movies rated this high or above on IMDB |
| **Check Interval** | 12 hours | How often to check all automation sources (advanced) |
| **Required Genres** | - | Only add movies matching at least one genre set (e.g., "Action, Crime & Drama") |
| **Ignored Genres** | - | Skip movies matching any genre set (e.g., "Horror, Comedy & Drama & Romance") |

**Genre Format:** Comma-separated sets, ampersand (&) for AND within sets. Example: `Action, Crime & Drama` means "Action OR (Crime AND Drama)".

---

## Automation Sources (Watchlists & Popular Lists)

### IMDB Watchlist
- **Purpose:** Import movies from public IMDB watchlists and custom lists
- **How it works:** Parses IMDB list pages for movie IDs, validates against filters
- **Settings:**
  - **Enabled** toggle
  - **URLs:** Add multiple IMDB watchlist/list URLs with individual enable toggles
- **URL formats supported:**
  - Watchlist: `https://www.imdb.com/user/ur12345678/watchlist`
  - Custom list: `https://www.imdb.com/list/ls012345678/`

### IMDB Charts Auto-Add
- **Purpose:** Automatically add movies from IMDB chart pages
- **Charts available:**
  - **In Theaters** - Currently playing in cinemas
  - **TOP 250** - IMDB's all-time top rated movies
  - **Box Office Top 10** - Current box office leaders
- **Note:** Different from IMDB Charts display (below) - this ADDS movies to your wanted list

### Trakt Watchlist
- **Purpose:** Sync with your Trakt.tv watchlist
- **How it works:** Uses OAuth 2.0 device code authentication to access your Trakt account
- **Setup:**
  1. Create a Trakt application at [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications)
  2. Enter your **Client ID** and **Client Secret** in the settings
  3. Click **"Authorize with Trakt"** to start the device code flow
  4. Visit the URL shown (trakt.tv/activate) and enter the code displayed
  5. Once authorized, CouchPotato will automatically sync your watchlist
- **Settings:**
  - **Enabled** toggle
  - **Client ID** - From your Trakt application
  - **Client Secret** - From your Trakt application
  - **Auth Token** (advanced) - Set automatically after authorization
  - **Refresh Token** (advanced) - Used for automatic token renewal

### Blu-ray.com
- **Purpose:** Import new Blu-ray releases
- **How it works:** Parses RSS feed and website for new releases
- **Settings:**
  - **Enabled** toggle
  - **Backlog** (advanced): Parse historical releases until minimum year is reached (runs once)

### iTunes
- **Purpose:** Import movies from iTunes Store feeds
- **How it works:** Parses Apple's public RSS feeds
- **Settings:**
  - **URLs:** Configure custom iTunes RSS feed URLs
- **Default URL:** Top 25 movies feed

### Letterboxd
- **Purpose:** Import movies from public Letterboxd watchlists
- **How it works:** Scrapes user watchlist pages
- **Settings:**
  - **Usernames:** Add Letterboxd usernames with enable toggles

### Popular Movies
- **Purpose:** Add movies currently popular in theaters
- **Source:** Pre-compiled list from S3 bucket
- **Settings:** Just an enable toggle - no configuration needed

### YTS Popular
- **Purpose:** Add popular movies from YTS torrent site
- **How it works:** Scrapes the YTS homepage for popular downloads
- **Settings:** Just an enable toggle

---

## Suggestions System (Display Tab)

The Suggestions system shows movies on the Suggestions page without adding them to your wanted list. Users can browse and manually add movies they're interested in.

### "For You" Suggestions
- **Purpose:** Personalized recommendations based on your library
- **How it works:**
  1. Picks random movies from your library
  2. Fetches TMDB recommendations for those movies
  3. Filters out movies already in your library
  4. Caches results for 1 hour
- **Settings:**
  - **Enabled** toggle

### IMDB Charts (Display)
- **Purpose:** Show IMDB chart data on the Suggestions page
- **Charts available:**
  - **In Theaters** - Currently playing in cinemas
  - **IMDB Top 250** - Highest rated movies
  - **Box Office Top 10** - Current earnings leaders
- **Note:** This only DISPLAYS movies - doesn't add them automatically

### Blu-ray New Releases (Display)
- **Purpose:** Show new Blu-ray releases on Suggestions page
- **Source:** Blu-ray.com RSS feed
- **Settings:**
  - **Enabled** toggle

---

## Technical Details

### Automation Pipeline
1. `automation.add_movies` event fires on interval
2. Each enabled provider's `getIMDBids()` is called
3. Movies pass through `isMinimalMovie()` filter
4. Passing movies are added via `movie.add` event
5. After adding, `movie.searcher.single` runs to search for downloads

### Caching
- Suggestion cache: 1 hour TTL
- Chart data cache: 3 days TTL
- Already-added movies tracked via properties to prevent duplicates

### API Endpoints
- `GET /api/{key}/automation.add_movies/` - Trigger manual automation scan
- `GET /api/{key}/automation.list/` - List movies found without adding
- `GET /api/{key}/suggestion.view/` - Get personalized suggestions
- `POST /api/{key}/suggestion.ignore/?imdb={id}` - Ignore a suggestion

---

## Recommended Configuration

### For most users:
1. Enable **IMDB Charts (Display)** with Box Office
2. Enable **"For You" Suggestions**
3. Enable **Blu-ray New Releases (Display)**
4. Optionally link an **IMDB Watchlist** if you curate one

### For power users:
1. Enable relevant automation sources
2. Configure strict genre filters to avoid unwanted adds
3. Set minimum rating to 7.0+ and votes to 1000+
4. Enable backlog on Blu-ray.com for one-time historical import

### Avoid enabling:
- Multiple overlapping sources (e.g., IMDB Charts Auto-Add AND Popular Movies)
- YTS Popular if you don't use that tracker

---

*Document created: 2026-02-12 by Eggbert 🥚*
*Updated: 2026-02-12 - Trakt OAuth now uses direct device code flow*
