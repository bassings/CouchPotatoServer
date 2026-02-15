# CouchPotato Accessibility Audit

**Date:** 2026-02-16  
**Auditor:** Eggbert  
**Target:** New htmx/Tailwind/Alpine.js UI (`/`)  
**Standard:** WCAG 2.1 AA

---

## Summary

| Category | Critical | Major | Minor | Pass |
|----------|----------|-------|-------|------|
| Keyboard Navigation | ~~2~~ 0 ✅ | ~~2~~ 0 ✅ | ~~1~~ 0 ✅ | 2 |
| Screen Reader Support | ~~3~~ 0 ✅ | ~~3~~ 0 ✅ | ~~2~~ 0 ✅ | 4 |
| Color Contrast | ~~1~~ 0 ✅ | ~~1~~ 0 ✅ | ~~1~~ 0 ✅ | - |
| Motion | ~~1~~ 0 ✅ | - | - | - |
| Focus Management | ~~2~~ 0 ✅ | - | - | - |
| Forms | - | ~~2~~ 0 ✅ | ~~1~~ 0 ✅ | - |
| **Total** | **0** ✅ | **0** ✅ | **0** ✅ | **6** |

**Status:** All 22 issues fixed in commit `af868cbb` (2026-02-16)

---

## Critical Issues (Must Fix)

### A11Y-001: Focus not trapped in modal dialogs
**WCAG:** 2.4.3 Focus Order (Level A)  
**Location:** `partials/movie_detail.html` (Trailer modal)  
**Problem:** When trailer modal opens, focus is not trapped inside. Users can tab behind the modal overlay.  
**Fix:**
```javascript
// Add focus trap using Alpine.js
x-init="$nextTick(() => { $el.querySelector('button, iframe').focus(); })"
@keydown.tab="trapFocus($event)"
@keydown.escape="showTrailer = false"
```
Also restore focus to trigger button on close.

### A11Y-002: Interactive elements hidden from keyboard
**WCAG:** 2.1.1 Keyboard (Level A)  
**Location:** `partials/movie_cards.html` (Refresh button)  
**Problem:** Refresh button uses `opacity-0 group-hover:opacity-100`, making it invisible and unreachable via keyboard.  
**Fix:**
```html
class="... opacity-0 group-hover:opacity-100 focus:opacity-100"
```
Add `focus:opacity-100` to show on keyboard focus.

### A11Y-003: No skip link to main content
**WCAG:** 2.4.1 Bypass Blocks (Level A)  
**Location:** `base.html`  
**Problem:** No skip link for keyboard users to bypass navigation.  
**Fix:** Add at start of `<body>`:
```html
<a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:bg-cp-accent focus:text-white focus:px-4 focus:py-2 focus:rounded">
  Skip to main content
</a>
```
Add `id="main-content"` to `<main>`.

### A11Y-004: Dynamic content changes not announced
**WCAG:** 4.1.3 Status Messages (Level AA)  
**Location:** All htmx regions  
**Problem:** When content loads via htmx, screen readers aren't notified.  
**Fix:** Add live regions:
```html
<div id="movie-grid" aria-live="polite" aria-atomic="false">
```
For loading states, add visually hidden text:
```html
<div class="sr-only" aria-live="assertive" x-text="loading ? 'Loading movies' : ''"></div>
```

### A11Y-005: Form inputs missing accessible labels
**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Location:** `wanted.html`, `add.html`, `logs.html`  
**Problem:** Search inputs have placeholder but no label.  
**Fix:**
```html
<label for="search-movies" class="sr-only">Filter movies</label>
<input id="search-movies" type="text" ...>
```
Or use `aria-label`:
```html
<input type="text" aria-label="Filter movies" ...>
```

### A11Y-006: Animations ignore reduced motion preference
**WCAG:** 2.3.3 Animation from Interactions (Level AAA, but best practice)  
**Location:** `base.html` (`<style>`)  
**Problem:** `fade-in` animation and transitions don't respect `prefers-reduced-motion`.  
**Fix:**
```css
@media (prefers-reduced-motion: reduce) {
  .fade-in { animation: none; }
  *, *::before, *::after { 
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

### A11Y-007: Loading spinner not announced
**WCAG:** 4.1.3 Status Messages (Level AA)  
**Location:** Multiple templates  
**Problem:** Loading spinners are visual only. Screen reader users don't know content is loading.  
**Fix:**
```html
<div role="status" aria-live="polite">
  <svg class="animate-spin ...">...</svg>
  <span class="sr-only">Loading...</span>
</div>
```

### A11Y-008: Modal close not returning focus
**WCAG:** 2.4.3 Focus Order (Level A)  
**Location:** `partials/movie_detail.html`  
**Problem:** After closing trailer modal, focus doesn't return to the button that opened it.  
**Fix:** Store reference to trigger element and restore focus:
```javascript
@click="triggeredBy = $el; showTrailer = true"
// On close:
@click="showTrailer = false; $nextTick(() => triggeredBy?.focus())"
```

### A11Y-009: Profile dropdown missing label
**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Location:** `partials/search_results.html`  
**Problem:** Profile `<select>` has no associated label.  
**Fix:**
```html
<label for="profile-{{ imdb }}" class="sr-only">Quality profile for {{ title }}</label>
<select id="profile-{{ imdb }}" ...>
```

---

## Major Issues (Should Fix)

### A11Y-010: Decorative SVGs not hidden from assistive tech
**WCAG:** 1.1.1 Non-text Content (Level A)  
**Location:** All templates  
**Problem:** Icon SVGs in buttons/links are read by screen readers as "graphic".  
**Fix:** Add `aria-hidden="true"` to decorative SVGs:
```html
<svg aria-hidden="true" class="w-4 h-4" ...>
```
For icon-only buttons, add visually hidden text:
```html
<button aria-label="Refresh metadata">
  <svg aria-hidden="true" ...>
```

### A11Y-011: Status badges not exposed to screen readers
**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Location:** `partials/movie_cards.html`  
**Problem:** "wanted" / "done" status badges are visual only. The `aria-label` on the link includes title but not status.  
**Fix:** Update aria-label:
```html
aria-label="{{ title }} ({{ year }}) - {{ status }}"
```

### A11Y-012: Table headers missing scope
**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Location:** `partials/movie_detail.html` (Releases table)  
**Problem:** `<th>` elements lack `scope="col"` attribute.  
**Fix:**
```html
<th scope="col" class="...">Name</th>
<th scope="col" class="...">Quality</th>
```

### A11Y-013: Insufficient focus indicator contrast
**WCAG:** 2.4.7 Focus Visible (Level AA)  
**Location:** All interactive elements  
**Problem:** Default browser focus outlines may not be visible on dark background.  
**Fix:** Add consistent focus styles:
```css
:focus-visible {
  outline: 2px solid #35c5f4;
  outline-offset: 2px;
}
```

### A11Y-014: Mobile menu button missing expanded state
**WCAG:** 4.1.2 Name, Role, Value (Level A)  
**Location:** `base.html` (mobile menu toggle)  
**Problem:** Button lacks `aria-expanded` attribute.  
**Fix:**
```html
<button @click="mobileMenu = !mobileMenu" 
        :aria-expanded="mobileMenu.toString()"
        aria-controls="mobile-menu"
        aria-label="Toggle menu">
```

### A11Y-015: Sidebar collapse button missing expanded state
**WCAG:** 4.1.2 Name, Role, Value (Level A)  
**Location:** `base.html` (sidebar toggle)  
**Problem:** Toggle button has `aria-label` but no expanded state.  
**Fix:**
```html
<button @click="sidebarCollapsed = !sidebarCollapsed"
        :aria-expanded="(!sidebarCollapsed).toString()"
        aria-label="Toggle sidebar">
```

### A11Y-016: Tab panel missing ARIA attributes
**WCAG:** 4.1.2 Name, Role, Value (Level A)  
**Location:** `suggestions.html`  
**Problem:** Tab buttons don't use `role="tab"`, `aria-selected`, or `role="tabpanel"`.  
**Fix:**
```html
<div role="tablist" class="flex gap-1...">
  <button role="tab" :aria-selected="activeTab === 'charts'" @click="...">Charts</button>
  <button role="tab" :aria-selected="activeTab === 'personal'" @click="...">For You</button>
</div>
<div role="tabpanel" x-show="activeTab === 'charts'" ...>
```

### A11Y-017: Delete confirmation uses native confirm()
**WCAG:** Best practice  
**Location:** `partials/movie_detail.html`  
**Problem:** Native `confirm()` is accessible but inconsistent with app design. Consider custom modal with proper focus management.  
**Recommendation:** Keep native `confirm()` for now (it's accessible), or implement a proper accessible dialog pattern.

---

## Minor Issues (Nice to Have)

### A11Y-018: Low contrast placeholder text
**WCAG:** 1.4.3 Contrast (Level AA)  
**Location:** All input placeholders  
**Problem:** `placeholder-cp-muted` (#6b6b78) on dark background may be below 4.5:1 ratio.  
**Fix:** Use slightly brighter placeholder color or rely on visible labels.

### A11Y-019: "No poster" text very low contrast
**WCAG:** 1.4.3 Contrast (Level AA)  
**Location:** `partials/movie_cards.html`  
**Problem:** `text-cp-muted/50` is decorative but should still be readable.  
**Fix:** Increase to `text-cp-muted/70` minimum.

### A11Y-020: Missing landmark for search results
**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Location:** `add.html`  
**Problem:** Search results section could benefit from `role="region"` with label.  
**Fix:**
```html
<div id="search-results" role="region" aria-label="Search results">
```

### A11Y-021: Table could benefit from caption
**WCAG:** 1.3.1 Info and Relationships (Level A)  
**Location:** `partials/movie_detail.html`  
**Problem:** Releases table has no `<caption>`.  
**Fix:**
```html
<table>
  <caption class="sr-only">Available releases for this movie</caption>
  ...
</table>
```

### A11Y-022: External link indicator
**WCAG:** Best practice (not strictly required)  
**Location:** IMDb links, trailer  
**Problem:** External links don't indicate they open in new window.  
**Fix:** Add visually hidden text or icon:
```html
<a href="..." target="_blank" rel="noopener">
  IMDb <span class="sr-only">(opens in new tab)</span>
</a>
```

---

## Passes ✅

1. **`<html lang="en">`** - Language declared ✅
2. **Navigation has `aria-label`** - Main and mobile nav labeled ✅
3. **`aria-current="page"`** - Active nav item marked ✅
4. **Poster images have `alt` text** - Title used as alt ✅
5. **Semantic HTML structure** - Proper headings, nav, main, table elements ✅
6. **Native form controls** - Using standard HTML inputs, buttons, selects ✅

---

## Implementation Priority

### Phase 1 (Critical) ✅ COMPLETE
- [x] A11Y-001: Focus trap in modals
- [x] A11Y-002: Keyboard-accessible refresh button
- [x] A11Y-003: Skip link
- [x] A11Y-005: Form input labels
- [x] A11Y-006: Reduced motion support

### Phase 2 (Major) ✅ COMPLETE
- [x] A11Y-004: Live regions for dynamic content
- [x] A11Y-007: Loading state announcements
- [x] A11Y-008: Focus restoration on modal close
- [x] A11Y-010: aria-hidden on decorative SVGs
- [x] A11Y-013: Focus indicator styles
- [x] A11Y-014/15: Expanded states on toggles

### Phase 3 (Polish) ✅ COMPLETE
- [x] A11Y-009: Profile dropdown labels
- [x] A11Y-011: Status in aria-label
- [x] A11Y-012: Table header scope
- [x] A11Y-016: Tab panel ARIA
- [x] Minor issues (A11Y-018 through A11Y-022)

---

## Testing Tools Recommended

- **axe DevTools** browser extension (automated scanning)
- **WAVE** browser extension (visual accessibility checker)
- **VoiceOver** (macOS) or **NVDA** (Windows) for manual screen reader testing
- **Lighthouse** accessibility audit (Chrome DevTools)
- Keyboard-only navigation testing

---

## Resources

- [WCAG 2.1 Quick Reference](https://www.w3.org/WAI/WCAG21/quickref/)
- [ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/)
- [Alpine.js a11y patterns](https://alpinejs.dev/component/dialog)
- [Tailwind a11y plugin](https://github.com/tailwindlabs/tailwindcss-forms)
