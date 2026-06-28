/**
 * Unit tests for the suggestion-loader pure logic module (the Suggestions
 * cold-load redesign). Covers the view-math the inline Alpine controller
 * delegates to: stage selection, progress %, and per-row checklist state.
 * Exercised by vitest and Stryker mutation testing, like the sibling CP.ui
 * modules. Boundary values pin every threshold and branch.
 */
import { describe, it, expect } from 'vitest';
import {
  SUGGESTION_STAGES,
  SUGGESTION_STAGES_CHARTS,
  SUGGESTION_STALL_AFTER,
  SUGGESTION_KEEP_WAITING_EXTENSION,
  suggestionStage,
  suggestionPct,
  suggestionStageDone,
  suggestionStageCurrent,
} from '../../../couchpotato/static/scripts/ui/suggestion-loader.js';

// A small, explicit stages fixture so threshold maths is obvious in assertions.
const STAGES = [
  { at: 0, label: 'A', sub: 'a' },
  { at: 10, label: 'B', sub: 'b' },
  { at: 20, label: 'C', sub: 'c' },
];

// ─── constants ────────────────────────────────────────────────────────────────

describe('SUGGESTION_STAGES / SUGGESTION_STALL_AFTER', () => {
  it('exposes five ascending stages starting at 0', () => {
    expect(SUGGESTION_STAGES).toHaveLength(5);
    expect(SUGGESTION_STAGES[0].at).toBe(0);
    const ats = SUGGESTION_STAGES.map((s) => s.at);
    expect(ats).toEqual([0, 12, 26, 42, 54]);
  });

  it('every stage has a label and a sub', () => {
    for (const stage of [...SUGGESTION_STAGES, ...SUGGESTION_STAGES_CHARTS]) {
      expect(stage.label.length).toBeGreaterThan(0);
      expect(stage.sub.length).toBeGreaterThan(0);
    }
  });

  it('the Charts stage set shares the For You thresholds (so the stall invariant holds for both)', () => {
    expect(SUGGESTION_STAGES_CHARTS).toHaveLength(SUGGESTION_STAGES.length);
    expect(SUGGESTION_STAGES_CHARTS.map((s) => s.at)).toEqual(SUGGESTION_STAGES.map((s) => s.at));
  });

  it('the Charts stage set carries no For-You-specific (library/personalisation) copy', () => {
    const text = SUGGESTION_STAGES_CHARTS.map((s) => `${s.label} ${s.sub}`)
      .join(' ')
      .toLowerCase();
    expect(text).not.toContain('your library');
    expect(text).not.toContain('what you like');
    expect(text).not.toContain('your matches');
  });

  // The named chart providers must match the backend reality: only TMDB, IMDb and
  // Blu-ray implement getChartList (charts.view). Rotten Tomatoes is a userscript
  // bookmarklet and Trakt is a watchlist provider — neither feeds the charts panel,
  // so naming them in either stage set is factually wrong.
  it('names only real chart providers in both stage sets', () => {
    for (const stages of [SUGGESTION_STAGES, SUGGESTION_STAGES_CHARTS]) {
      const text = stages
        .map((s) => s.sub)
        .join(' ')
        .toLowerCase();
      expect(text).not.toContain('rotten tomatoes');
      expect(text).not.toContain('trakt');
    }
  });

  it('stalls after 60 seconds by default', () => {
    expect(SUGGESTION_STALL_AFTER).toBe(60);
  });

  // Regression guard for the stall/stage contradiction: if the stall fired
  // before the final stage threshold, the "Still working" heading would clash
  // with a later checklist row lighting up. Keep stall >= the last stage `at`.
  it('does not stall before the staged narrative finishes (either tab)', () => {
    for (const stages of [SUGGESTION_STAGES, SUGGESTION_STAGES_CHARTS]) {
      expect(SUGGESTION_STALL_AFTER).toBeGreaterThanOrEqual(stages[stages.length - 1].at);
    }
  });

  it('extends the stall grace period by 30 seconds on keep-waiting', () => {
    expect(SUGGESTION_KEEP_WAITING_EXTENSION).toBe(30);
  });
});

// ─── suggestionStage ──────────────────────────────────────────────────────────

describe('suggestionStage', () => {
  it('returns the first stage at elapsed 0', () => {
    expect(suggestionStage(0, STAGES)).toBe(STAGES[0]);
  });

  it('returns the first stage for negative/sub-threshold elapsed', () => {
    expect(suggestionStage(-5, STAGES)).toBe(STAGES[0]);
    expect(suggestionStage(9, STAGES)).toBe(STAGES[0]);
  });

  it('advances exactly at a threshold (>= boundary, not >)', () => {
    expect(suggestionStage(10, STAGES)).toBe(STAGES[1]);
    expect(suggestionStage(20, STAGES)).toBe(STAGES[2]);
  });

  it('holds a stage until the next threshold is reached', () => {
    expect(suggestionStage(19, STAGES)).toBe(STAGES[1]);
  });

  it('returns the last stage well beyond the final threshold', () => {
    expect(suggestionStage(9999, STAGES)).toBe(STAGES[2]);
  });

  it('defaults to the real SUGGESTION_STAGES', () => {
    expect(suggestionStage(0)).toBe(SUGGESTION_STAGES[0]);
    expect(suggestionStage(26)).toBe(SUGGESTION_STAGES[2]);
    expect(suggestionStage(100)).toBe(SUGGESTION_STAGES[4]);
  });
});

// ─── suggestionPct ────────────────────────────────────────────────────────────

describe('suggestionPct', () => {
  it('snaps to 100 once loaded, regardless of elapsed', () => {
    expect(suggestionPct(0, true)).toBe(100);
    expect(suggestionPct(3, true)).toBe(100);
  });

  it('is 0 at the very start when not loaded', () => {
    expect(suggestionPct(0, false)).toBe(0);
  });

  it('eases toward the ceiling proportionally to elapsed', () => {
    // 30/60*92 = 46
    expect(suggestionPct(30, false)).toBe(46);
    // 60/60*92 = 92
    expect(suggestionPct(60, false)).toBe(92);
  });

  it('caps at 92 (never claims done) for long waits — Math.min, not max', () => {
    expect(suggestionPct(100, false)).toBe(92);
    expect(suggestionPct(10000, false)).toBe(92);
  });

  it('rounds to the nearest integer', () => {
    // 5/60*92 = 7.666… → 8
    expect(suggestionPct(5, false)).toBe(8);
  });
});

// ─── suggestionStageDone ──────────────────────────────────────────────────────

describe('suggestionStageDone', () => {
  it('is true for every row once loaded', () => {
    expect(suggestionStageDone(0, 0, true, STAGES)).toBe(true);
    expect(suggestionStageDone(2, 0, true, STAGES)).toBe(true);
  });

  it('is true once the NEXT stage threshold is reached', () => {
    // row 0 done when elapsed >= STAGES[1].at (10)
    expect(suggestionStageDone(0, 10, false, STAGES)).toBe(true);
    expect(suggestionStageDone(1, 20, false, STAGES)).toBe(true);
  });

  it('is false before the next threshold (>= boundary)', () => {
    expect(suggestionStageDone(0, 9, false, STAGES)).toBe(false);
    expect(suggestionStageDone(1, 19, false, STAGES)).toBe(false);
  });

  it('is false for the last row even at huge elapsed (no next stage)', () => {
    expect(suggestionStageDone(2, 9999, false, STAGES)).toBe(false);
  });

  it('defaults to the real SUGGESTION_STAGES', () => {
    // row 0 done once elapsed >= 12 (SUGGESTION_STAGES[1].at)
    expect(suggestionStageDone(0, 12, false)).toBe(true);
    expect(suggestionStageDone(0, 11, false)).toBe(false);
  });
});

// ─── suggestionStageCurrent ───────────────────────────────────────────────────

describe('suggestionStageCurrent', () => {
  it('is false for every row once loaded', () => {
    expect(suggestionStageCurrent(0, 0, true, STAGES)).toBe(false);
    expect(suggestionStageCurrent(1, 15, true, STAGES)).toBe(false);
  });

  it('is true only for the active stage row', () => {
    // elapsed 15 → active stage is index 1
    expect(suggestionStageCurrent(0, 15, false, STAGES)).toBe(false);
    expect(suggestionStageCurrent(1, 15, false, STAGES)).toBe(true);
    expect(suggestionStageCurrent(2, 15, false, STAGES)).toBe(false);
  });

  it('marks row 0 current at the start', () => {
    expect(suggestionStageCurrent(0, 0, false, STAGES)).toBe(true);
  });

  it('marks the last row current beyond the final threshold', () => {
    expect(suggestionStageCurrent(2, 9999, false, STAGES)).toBe(true);
  });

  it('defaults to the real SUGGESTION_STAGES', () => {
    expect(suggestionStageCurrent(2, 26, false)).toBe(true);
    expect(suggestionStageCurrent(2, 26, false, SUGGESTION_STAGES)).toBe(true);
  });
});
