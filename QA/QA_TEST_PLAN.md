# CouchPotato QA Test Plan

**Application:** CouchPotato Movie Management System
**Version:** v3.0.11 (docker)
**Stack:** Python 3, FastAPI, htmx + Tailwind + Alpine.js

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

### 2.1 Adding a Movie to Wanted List
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
- [ ] Add movie already in library
- [ ] Add movie already wanted

### 2.2 Searching for Movies
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

### 2.3 Managing Wanted Movies
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

### 2.4 Checking Download Status
**Locations:**
- Movie detail page shows releases table
- Status badges on movie cards

**Test Cases:**
- [ ] Movies with no releases show empty state
- [ ] Snatched releases show correct status
- [ ] Done releases show success status
- [ ] Release quality labels display correctly

### 2.5 Configuring Settings/Providers
**Test Cases:**
- [ ] Each settings tab loads correctly
- [ ] Form inputs accept valid values
- [ ] Form validation rejects invalid values
- [ ] Save button persists changes
- [ ] Test buttons work (Newznab, etc.)
- [ ] Jackett sync imports indexers
- [ ] Advanced mode shows additional options

---

## 3. Edge Cases to Test

### 3.1 Empty States
- [ ] Empty Wanted list
- [ ] Empty Available list
- [ ] Empty search results
- [ ] Empty suggestions
- [ ] Movie with no poster
- [ ] Movie with no year
- [ ] Movie with no plot

### 3.2 Long Content
- [ ] Very long movie titles
- [ ] Very long plot descriptions
- [ ] Many genres
- [ ] Long actor lists

### 3.3 Special Characters
- [ ] Titles with colons (e.g., "Star Wars: A New Hope")
- [ ] Titles with ampersands (e.g., "Barb & Star")
- [ ] Titles with quotes
- [ ] Non-Latin characters
- [ ] Emoji in titles

### 3.4 Network/API Errors
- [ ] TMDB API unavailable
- [ ] Poster image 404
- [ ] Slow network response
- [ ] API rate limiting

---

## 4. UI/UX Checklist

### 4.1 Responsive Design
- [ ] Mobile viewport (< 640px)
- [ ] Tablet viewport (640px - 1024px)
- [ ] Desktop viewport (> 1024px)
- [ ] Sidebar collapse on mobile

### 4.2 Accessibility
- [ ] Keyboard navigation
- [ ] Focus states visible
- [ ] Alt text on images
- [ ] Semantic HTML structure
- [ ] Color contrast

### 4.3 Performance
- [ ] Initial page load time
- [ ] Image lazy loading
- [ ] htmx partial updates
- [ ] Filter/search responsiveness

---

## 5. API Endpoints to Test

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

---

## 6. Integration Testing

### 6.1 Downstream Services
- [ ] TMDB API for movie search
- [ ] TMDB API for movie info
- [ ] Jackett for indexer sync
- [ ] Usenet providers (Newznab)
- [ ] Torrent providers

### 6.2 Mocking Strategy
When services unavailable:
1. Use recorded API responses
2. Check error handling displays
3. Verify graceful degradation

---

## 7. Test Data

### 7.1 Sample Movies for Testing
- Short title: "Up" (2009)
- Long title: "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb"
- Special chars: "Amélie" (2001)
- Colon in title: "Star Wars: A New Hope"
- Future release: Movies with release date in future
- No year: Movies without release year

### 7.2 Edge Case Queries
- Empty string
- Single space
- Unicode: "日本語"
- SQL injection: `'; DROP TABLE--`
- XSS: `<script>alert('xss')</script>`

---

## 8. Regression Tests

Run after each release:
1. All navigation links work
2. Movie search returns results
3. Movie add completes successfully
4. Movie detail pages load
5. Settings changes persist
6. Filters work correctly
7. Delete with confirmation works
8. Logs display in real-time
