// Pure filtering/formatting logic for the Wanted movie list (wanted.html).
// Extracted from the inline `movieList()` Alpine component so it can be unit-
// and mutation-tested. The component delegates its per-card decision here.

/**
 * Decide whether a movie card is visible under the current search + filter.
 * @param {{title?: string, status?: string, hasReleases?: boolean}} card
 * @param {{query?: string, filterStatus?: string}} criteria
 * @returns {boolean}
 */
export function matchesFilter(card, criteria) {
  const q = (criteria.query || '').toLowerCase().trim();
  const title = (card.title || '').toLowerCase();
  const matchSearch = !q || title.includes(q);

  const filterStatus = criteria.filterStatus || '';
  let matchStatus;
  if (!filterStatus) {
    matchStatus = true;
  } else if (filterStatus === 'available') {
    matchStatus = !!card.hasReleases;
  } else if (filterStatus === 'wanted') {
    matchStatus = !card.hasReleases;
  } else {
    matchStatus = (card.status || '') === filterStatus;
  }

  return matchSearch && matchStatus;
}

/**
 * Build the "N of M movies" / "M movies" count label.
 * @param {number} visible
 * @param {number} total
 * @param {boolean} hasFilter  true when a search or status filter is active
 * @returns {string}
 */
export function formatCount(visible, total, hasFilter) {
  return hasFilter ? `${visible} of ${total} movies` : `${total} movies`;
}

/**
 * Normalize a raw year for display: a falsy or 0 year becomes "TBA".
 * @param {number|null|undefined} rawYear
 * @returns {string}
 */
export function normalizeYear(rawYear) {
  return (rawYear && rawYear !== 0) ? String(rawYear) : 'TBA';
}
