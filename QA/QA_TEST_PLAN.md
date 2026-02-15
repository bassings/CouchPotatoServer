# CouchPotato QA Test Plan

**Application:** CouchPotato Movie Management System
**Version:** v3.0.11 (docker)
**Stack:** Python 3, FastAPI, htmx + Tailwind + Alpine.js
**Last Updated:** 2026-02-16

---

## 1. Screen Inventory

### 1.1 Main Navigation Pages
| Page | URL | Status | Notes |
|------|-----|--------|-------|
| Wanted | /wanted/ | ✓ | Default landing page, shows wanted movies |
| Available | /available/ | ✓ | Shows downloaded/available movies |
| Suggestions | /suggestions/ | ✓ | Charts and personalized suggestions |
| Add Movie | /add/ | ✓ | TMDB search to add movies |
| Settings | /settings/ | ✓ | Configuration with tabbed interface |
| Setup Wizard | /wizard/ | ✓ | 6-step setup wizard |
| Classic UI | /old/ | ⚠ | Requires separate authentication |

### 1.2 Detail Pages
| Page | URL Pattern | Status | Notes |
|------|-------------|--------|-------|
| Movie Detail | /movie/{id}/ | ✓ | Shows movie info, actions, releases |

### 1.3 Settings Tabs
| Tab | Purpose |
|-----|---------|
| General | Server, authentication, updates |
| Searchers | Usenet/torrent providers, Jackett integration |
| Downloaders | SABnzbd, qBittorrent, etc. |
| Renamer | File organization rules |
| Notifications | Push notifications, email, etc. |
| Library | Movie library paths |
| Suggestions | Suggestion sources |
| Logs | Live log viewer |

---

## 2. User Flows

### 2.1 New User Onboarding (Setup Wizard)
**Priority:** HIGH — First-time user experience

**Happy Path:**
1. Open app with no existing configuration
2. Automatically redirected to Setup Wizard
3. Complete all wizard steps
4. Settings persist after wizard completion
5. App is functional with configured settings

**Test Cases:**
- [ ] Fresh install redirects to wizard (no config present)
- [ ] Wizard Step 1: Welcome/intro displays correctly
- [ ] Wizard Step 2: Directory/library path configuration
  - [ ] Browse button works
  - [ ] Invalid path shows error
  - [ ] Valid path accepts and saves
- [ ] Wizard Step 3: Downloader setup
  - [ ] All downloader types available in dropdown
  - [ ] Test connection button works
  - [ ] Invalid credentials show meaningful error
  - [ ] Successful test shows confirmation
- [ ] Wizard Step 4: Searcher/provider setup
  - [ ] Newznab provider configuration
  - [ ] Torrent provider configuration
  - [ ] Test buttons validate connections
- [ ] Wizard Step 5: Quality profile selection
  - [ ] Default profiles displayed
  - [ ] Can select/modify quality preferences
- [ ] Wizard Step 6: Summary/completion
  - [ ] Shows summary of configured settings
  - [ ] Finish button saves all settings
- [ ] Post-wizard: All settings persisted in config
- [ ] Post-wizard: App navigates to main UI
- [ ] Post-wizard: Configured services are functional
- [ ] Re-running wizard updates existing settings
- [ ] Canceling wizard mid-way doesn't corrupt config
- [ ] Wizard accessible via Settings after initial setup

---

### 2.2 Adding a Movie to Wanted List
**Happy Path:**
1. Navigate to Add Movie page
2. Enter movie title in search box
3. Wait for TMDB results
4. Select quality profile from dropdown
5. Click "Add" button
6. Movie appears in Wanted list

**Test Cases:**
- [ ] Search with exact title
- [ ] Search with partial title
- [ ] Search with year (e.g., "Matrix 1999")
- [ ] Search with special characters (e.g., "Amélie")
- [ ] Search with very long title
- [ ] Search with no results
- [ ] Add movie already in library (should warn/prevent)
- [ ] Add movie already wanted (should warn/prevent)
- [ ] Add movie with future release date
- [ ] Quality profile dropdown shows all profiles
- [ ] Selected quality persists with movie

---

### 2.3 Suggestions Section
**Priority:** HIGH — Discovery feature

**Suggestion Sources to Test:**
- [ ] IMDB Charts (Top 250, Popular, etc.)
- [ ] TMDB Charts (Popular, Now Playing, Upcoming)
- [ ] Trakt Charts (Trending, Popular, Anticipated)
- [ ] Rotten Tomatoes (if available)
- [ ] Personal suggestions (based on library)
- [ ] Any other configured suggestion providers

**Test Cases:**
- [ ] Each suggestion provider loads data
- [ ] Provider shows meaningful error if API unavailable
- [ ] Movie cards display correctly (poster, title, year)
- [ ] "Add" button on suggestion adds to Wanted
- [ ] Already-added movies show different state
- [ ] Already-in-library movies show different state
- [ ] Pagination/infinite scroll works (if applicable)
- [ ] Refresh button fetches new data
- [ ] Empty provider shows helpful message
- [ ] Provider toggle (enable/disable) works in Settings
- [ ] Provider order/priority respected

---

### 2.4 Searching for Movies
**Happy Path:**
1. Navigate to Add Movie page
2. Type in search box
3. Results appear after typing stops (debounced)
4. Each result shows poster, title, year, quality selector

**Test Cases:**
- [ ] Empty search (should show placeholder)
- [ ] Single character search
- [ ] Special characters (& " ' etc.)
- [ ] Non-ASCII characters (日本語, émojis)
- [ ] Very long query
- [ ] Network timeout handling
- [ ] TMDB rate limit handling

---

### 2.5 Managing Wanted Movies
**Actions Available:**
- Filter by status (All/Wanted/Done)
- Text search filter
- Click to view details
- Refresh movie info
- Delete movie
- Watch trailer

**Test Cases:**
- [ ] Filter buttons work correctly
- [ ] Text filter is case-insensitive
- [ ] Text filter updates count
- [ ] Click movie opens detail page
- [ ] Detail page shows correct movie info
- [ ] Refresh updates movie metadata
- [ ] Delete removes movie with confirmation
- [ ] Trailer plays in modal
- [ ] Bulk selection (if available)
- [ ] Sort options work correctly

---

### 2.6 Movie Lifecycle & State Transitions
**Priority:** HIGH — Core functionality

**States:**
- Wanted → Snatched → Downloaded → Done
- Wanted → Failed (search/snatch failure)

**Test Cases:**
- [ ] New movie starts in "Wanted" state
- [ ] Successful snatch moves to "Snatched" state
- [ ] Completed download moves to "Downloaded" state
- [ ] Renamer processing moves to "Done" state
- [ ] Failed snatch shows failure reason
- [ ] Can retry failed movies
- [ ] Can manually change movie state
- [ ] State history visible in movie detail
- [ ] Quality upgrades: Can re-search for better quality
- [ ] State badges display correctly on cards

---

### 2.7 Manual Search & Snatch
**Priority:** HIGH — Power user feature

**Test Cases:**
- [ ] Manual search button on movie detail page
- [ ] Search returns results from all enabled providers
- [ ] Results show: release name, size, quality, provider, age
- [ ] Results sortable by quality/size/age
- [ ] Can filter results by quality
- [ ] Snatch button initiates download
- [ ] Successful snatch shows confirmation
- [ ] Failed snatch shows meaningful error
- [ ] Duplicate/already-snatched releases indicated
- [ ] Provider health shown (up/down status)

---

### 2.8 Checking Download Status
**Locations:**
- Movie detail page shows releases table
- Status badges on movie cards

**Test Cases:**
- [ ] Movies with no releases show empty state
- [ ] Snatched releases show correct status
- [ ] Done releases show success status
- [ ] Release quality labels display correctly
- [ ] Download progress shown (if available from downloader)
- [ ] Failed downloads show error reason

---

## 3. Settings Testing

### 3.1 Settings — General Structure
**Test Cases:**
- [ ] Each settings tab loads correctly
- [ ] Tab switching doesn't lose unsaved changes (or warns)
- [ ] Save button persists changes
- [ ] Cancel/Reset reverts to saved values
- [ ] Form validation rejects invalid values
- [ ] Validation errors clearly indicate which field
- [ ] Required fields marked appropriately
- [ ] Advanced mode toggle shows/hides advanced options
- [ ] Settings persist across app restarts

---

### 3.2 Settings — Descriptions & Help Text
**Priority:** HIGH — User experience

**Test Cases:**
- [ ] Every setting has a description/help text
- [ ] Descriptions are meaningful and help user understand purpose
- [ ] Descriptions explain when/why to change the setting
- [ ] Technical settings explain expected format (e.g., URLs, ports)
- [ ] Tooltips or info icons provide additional context where needed
- [ ] No "undefined" or blank descriptions
- [ ] Placeholder text provides examples where helpful
- [ ] Units are specified (e.g., "minutes", "MB")

---

### 3.3 Settings — Searchers Tab
**Priority:** HIGH — Critical for functionality

**Newznab Providers:**
- [ ] Can add new Newznab provider
- [ ] Can configure multiple Newznab providers
- [ ] Each provider has: Name, Host, API Key fields
- [ ] Test button for each individual provider
- [ ] Test success shows confirmation message
- [ ] Test failure shows meaningful error:
  - [ ] Invalid URL format
  - [ ] Connection refused/timeout
  - [ ] Invalid API key
  - [ ] API rate limited
- [ ] Can enable/disable individual providers
- [ ] Can delete providers
- [ ] Can reorder provider priority
- [ ] Provider-specific advanced settings accessible

**TorrentPotato Providers:**
- [ ] Can add new TorrentPotato provider
- [ ] Can configure multiple TorrentPotato providers
- [ ] Each provider has: Name, Host, Passkey fields
- [ ] Test button for each individual provider
- [ ] Test success shows confirmation
- [ ] Test failure shows meaningful error
- [ ] Multi-entry UI clearly shows all configured providers
- [ ] Success/error status shown per-provider (not just overall)

**Jackett Integration:**
- [ ] Jackett URL configuration
- [ ] Jackett API key configuration
- [ ] Test connection button
- [ ] "Sync from Jackett" button imports indexers
- [ ] Sync shows count of imported indexers
- [ ] Sync description text is meaningful (not "undefined")
- [ ] Duplicate indexers handled gracefully
- [ ] Failed sync shows helpful error

**Other Torrent Providers:**
- [ ] Each provider type configurable
- [ ] Test buttons work for each
- [ ] Error messages specific to provider type

---

### 3.4 Settings — Downloaders Tab
**Priority:** HIGH — Critical for functionality

**For Each Downloader Type (SABnzbd, NZBGet, qBittorrent, Transmission, Deluge, etc.):**
- [ ] Can configure connection details (host, port, username, password)
- [ ] Test button validates connection
- [ ] Test success shows confirmation with downloader version
- [ ] Test failure shows meaningful error:
  - [ ] Connection refused
  - [ ] Invalid credentials
  - [ ] Wrong port
  - [ ] SSL/TLS issues
  - [ ] Timeout
- [ ] Category/label configuration works
- [ ] Priority settings work
- [ ] Can enable/disable downloader
- [ ] Multiple downloaders can be configured
- [ ] Downloader priority/failover order works

---

### 3.5 Settings — Notifications Tab
**Priority:** MEDIUM

**For Each Notification Provider:**
- [ ] Can configure provider credentials/settings
- [ ] Test button sends test notification
- [ ] Test success confirms notification received
- [ ] Test failure shows meaningful error:
  - [ ] Invalid credentials
  - [ ] Service unavailable
  - [ ] Rate limited
- [ ] Can configure which events trigger notifications:
  - [ ] Movie added
  - [ ] Movie snatched
  - [ ] Movie downloaded
  - [ ] Movie failed
- [ ] Can enable/disable individual providers
- [ ] Notification message customization (if available)

**Providers to Test:**
- [ ] Email/SMTP
- [ ] Pushover
- [ ] Pushbullet
- [ ] Telegram
- [ ] Discord
- [ ] Slack
- [ ] Plex
- [ ] Trakt
- [ ] Any other configured providers

---

### 3.6 Settings — Renamer Tab
**Test Cases:**
- [ ] Rename pattern configuration
- [ ] Folder pattern configuration
- [ ] Preview/dry-run shows expected output
- [ ] Special character handling in patterns
- [ ] Token/variable reference available
- [ ] Invalid pattern shows validation error
- [ ] File extension handling
- [ ] Cleanup original files option
- [ ] Permission/ownership settings

---

### 3.7 Settings — Library Tab
**Test Cases:**
- [ ] Can add library paths
- [ ] Browse button works for path selection
- [ ] Invalid path shows error
- [ ] Can remove library paths
- [ ] Scan library button initiates scan
- [ ] Scan progress shown
- [ ] Scan results summarized (found X movies)
- [ ] Duplicate detection options

---

### 3.8 Settings — Quality Profiles
**Test Cases:**
- [ ] Default profiles exist
- [ ] Can create new profiles
- [ ] Can edit existing profiles
- [ ] Can delete custom profiles (not defaults)
- [ ] Quality order/priority configurable
- [ ] Size limits configurable
- [ ] Can set as default profile
- [ ] Profile changes apply to new movies

---

### 3.9 Settings — Logs Tab
**Test Cases:**
- [ ] Live log streaming works
- [ ] Log entries appear in real-time
- [ ] Log level filtering (Debug, Info, Warning, Error)
- [ ] Text search/filter in logs
- [ ] Clear logs button
- [ ] Log timestamps accurate
- [ ] Long log entries display correctly
- [ ] Auto-scroll to bottom (with toggle)
- [ ] Export/download logs (if available)

---

## 4. Edge Cases to Test

### 4.1 Empty States
- [ ] Empty Wanted list
- [ ] Empty Available list
- [ ] Empty search results
- [ ] Empty suggestions (no providers configured)
- [ ] Movie with no poster
- [ ] Movie with no year
- [ ] Movie with no plot

### 4.2 Long Content
- [ ] Very long movie titles
- [ ] Very long plot descriptions
- [ ] Many genres
- [ ] Long actor lists

### 4.3 Special Characters
- [ ] Titles with colons (e.g., "Star Wars: A New Hope")
- [ ] Titles with ampersands (e.g., "Barb & Star")
- [ ] Titles with quotes
- [ ] Non-Latin characters
- [ ] Emoji in titles

### 4.4 Network/API Errors
- [ ] TMDB API unavailable
- [ ] Poster image 404
- [ ] Slow network response
- [ ] API rate limiting
- [ ] Partial API response

### 4.5 Data Integrity
- [ ] Corrupt database entry handling
- [ ] Missing required fields in data
- [ ] Orphaned release records
- [ ] Database backup/restore

---

## 5. Authentication & Security

### 5.1 API Key
- [ ] Valid API key allows access
- [ ] Invalid API key returns 401
- [ ] Missing API key returns 401
- [ ] API key shown/hidden in settings

### 5.2 Session Management
- [ ] Login creates session
- [ ] Session timeout behavior
- [ ] Logout clears session
- [ ] Multiple concurrent sessions

---

## 6. UI/UX Checklist

### 6.1 Responsive Design
- [ ] Mobile viewport (< 640px)
- [ ] Tablet viewport (640px - 1024px)
- [ ] Desktop viewport (> 1024px)
- [ ] Sidebar collapse on mobile

### 6.2 Accessibility
**Full audit:** See `ACCESSIBILITY_AUDIT.md` for detailed findings.

**Core Checks:**
- [ ] Keyboard navigation (all interactive elements reachable)
- [ ] Skip link to main content
- [ ] Focus states visible on all interactive elements
- [ ] Focus trapped in modals
- [ ] Alt text on images
- [ ] Semantic HTML structure
- [ ] ARIA labels on form controls
- [ ] ARIA live regions for dynamic content
- [ ] Color contrast (WCAG 2.1 AA — 4.5:1 minimum)
- [ ] Reduced motion support (`prefers-reduced-motion`)
- [ ] Screen reader testing (VoiceOver/NVDA)

**Tools:**
- axe DevTools browser extension
- Lighthouse accessibility audit
- Manual keyboard-only testing

### 6.3 Performance
- [ ] Initial page load time (< 3s target)
- [ ] Image lazy loading
- [ ] htmx partial updates efficient
- [ ] Filter/search responsiveness (< 200ms)
- [ ] Large library handling (500+ movies)

---

## 7. API Endpoints to Test

| Endpoint | Method | Purpose |
|----------|--------|---------|
| /api/{key}/movie.list/ | GET | List movies |
| /api/{key}/media.get/ | GET | Get single movie |
| /api/{key}/movie.search | GET | Search TMDB |
| /api/{key}/movie.add | POST | Add movie |
| /api/{key}/media.delete | POST | Delete movie |
| /api/{key}/media.refresh | POST | Refresh metadata |
| /api/{key}/movie.trailer | GET | Get trailer URL |
| /api/{key}/suggestion.view | GET | Get suggestions |
| /api/{key}/charts.view | GET | Get chart data |
| /api/{key}/searcher.test | POST | Test searcher |
| /api/{key}/downloader.test | POST | Test downloader |
| /api/{key}/notification.test | POST | Test notification |

---

## 8. Integration Testing

### 8.1 Downstream Services
- [ ] TMDB API for movie search
- [ ] TMDB API for movie info/posters
- [ ] Jackett for indexer sync
- [ ] Usenet providers (Newznab)
- [ ] Torrent providers (TorrentPotato, etc.)
- [ ] Download clients (SABnzbd, qBittorrent, etc.)
- [ ] Notification services

### 8.2 Mocking Strategy
When services unavailable:
1. Use recorded API responses
2. Check error handling displays
3. Verify graceful degradation
4. Document which tests require live services

---

## 9. Test Data

### 9.1 Sample Movies for Testing
- Short title: "Up" (2009)
- Long title: "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb"
- Special chars: "Amélie" (2001)
- Colon in title: "Star Wars: A New Hope"
- Future release: Movies with release date in future
- No year: Movies without release year
- No poster: Obscure movie without TMDB poster

### 9.2 Edge Case Queries
- Empty string
- Single space
- Unicode: "日本語"
- SQL injection: `'; DROP TABLE--`
- XSS: `<script>alert('xss')</script>`

---

## 10. Regression Tests

**Run after each release:**
1. All navigation links work
2. Movie search returns results
3. Movie add completes successfully
4. Movie detail pages load with correct info
5. Settings changes persist across restart
6. Filters work correctly
7. Delete with confirmation works
8. Test buttons return meaningful results
9. Suggestions load from all providers
10. Manual search returns results
11. Logs display in real-time

---

## 11. Test Execution Log

| Date | Version | Tester | Sections Tested | Pass/Fail | Notes |
|------|---------|--------|-----------------|-----------|-------|
| 2026-02-16 | v3.0.11 | QA Auto | 1,2,3,4,5 | Partial | 2 bugs fixed, 5 open |
| | | | | | |

---

## 12. Known Issues / Won't Fix

Document any issues that are known but not planned for immediate fix:

| Issue | Reason | Workaround |
|-------|--------|------------|
| Classic UI requires separate auth | Architecture limitation | Use new UI |
| | | |
