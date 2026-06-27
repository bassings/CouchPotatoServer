/**
 * Unit tests for the extracted Wanted-list filter logic.
 * These import the REAL module that wanted.html delegates to, so they (and
 * Stryker mutation testing) exercise production code rather than a mock.
 */
import { describe, it, expect } from 'vitest';
import { matchesFilter, formatCount, normalizeYear } from '../../../couchpotato/static/scripts/ui/movie-filter.js';

describe('matchesFilter', () => {
  const card = { title: 'The Matrix', status: 'active', hasReleases: false };

  it('matches everything when no query and no status', () => {
    expect(matchesFilter(card, {})).toBe(true);
  });

  it('matches case-insensitively and trims the query', () => {
    expect(matchesFilter(card, { query: '  MATRIX ' })).toBe(true);
    expect(matchesFilter(card, { query: 'matr' })).toBe(true);
  });

  it('rejects a non-substring query', () => {
    expect(matchesFilter(card, { query: 'inception' })).toBe(false);
  });

  it('filterStatus "available" requires hasReleases', () => {
    expect(matchesFilter({ ...card, hasReleases: true }, { filterStatus: 'available' })).toBe(true);
    expect(matchesFilter({ ...card, hasReleases: false }, { filterStatus: 'available' })).toBe(false);
  });

  it('filterStatus "wanted" requires NOT hasReleases', () => {
    expect(matchesFilter({ ...card, hasReleases: false }, { filterStatus: 'wanted' })).toBe(true);
    expect(matchesFilter({ ...card, hasReleases: true }, { filterStatus: 'wanted' })).toBe(false);
  });

  it('an explicit status filter matches the card status exactly', () => {
    expect(matchesFilter({ ...card, status: 'done' }, { filterStatus: 'done' })).toBe(true);
    expect(matchesFilter({ ...card, status: 'active' }, { filterStatus: 'done' })).toBe(false);
  });

  it('requires BOTH search and status to match', () => {
    const c = { title: 'Dune', status: 'active', hasReleases: true };
    expect(matchesFilter(c, { query: 'dune', filterStatus: 'available' })).toBe(true);
    expect(matchesFilter(c, { query: 'dune', filterStatus: 'wanted' })).toBe(false);
    expect(matchesFilter(c, { query: 'nope', filterStatus: 'available' })).toBe(false);
  });

  it('tolerates missing card fields', () => {
    expect(matchesFilter({}, {})).toBe(true);
    expect(matchesFilter({}, { query: 'x' })).toBe(false);
  });
});

describe('formatCount', () => {
  it('shows "N of M movies" when a filter is active', () => {
    expect(formatCount(3, 10, true)).toBe('3 of 10 movies');
  });

  it('shows "M movies" when no filter is active', () => {
    expect(formatCount(10, 10, false)).toBe('10 movies');
  });
});

describe('normalizeYear', () => {
  it('returns the year as a string when valid', () => {
    expect(normalizeYear(2024)).toBe('2024');
    expect(normalizeYear(1999)).toBe('1999');
  });

  it('returns "TBA" for 0, null, or undefined', () => {
    expect(normalizeYear(0)).toBe('TBA');
    expect(normalizeYear(null)).toBe('TBA');
    expect(normalizeYear(undefined)).toBe('TBA');
  });
});
