// Pure, framework-free helpers for the Suggestions communicative-loading panel
// (the cold-load redesign — see couchpotato/ui/templates/suggestions.html).
//
// The stateful Alpine controller cpSuggestionLoader() owns the timer, htmx
// retrigger and the loaded/failed/stalled flags; it delegates all of its view
// math to the pure functions below so the staging/progress logic is unit- and
// mutation-tested like the other CP.ui modules (category-editor, profile-editor).

// Staged status messages, keyed by the elapsed-second threshold at which each
// becomes the active stage. Ordered, ascending `at`. There is one set per tab so
// the copy is accurate: the For You call personalises from your library AND pulls
// chart sources, whereas the Charts call only pulls external chart providers —
// showing "Analysing your library" on the Charts tab would be factually wrong.
// Both sets MUST share the same thresholds so the stall invariant (below) holds
// for either tab.

// For You (personal): library personalisation + chart sources.
export const SUGGESTION_STAGES = [
  { at: 0, label: 'Connecting to sources', sub: 'Reaching TheMovieDB and chart providers' },
  { at: 12, label: 'Analysing your library', sub: 'Learning what you like' },
  { at: 26, label: 'Fetching chart sources', sub: 'TheMovieDB · IMDb · Blu-ray'},
  { at: 42, label: 'Ranking your matches', sub: 'Scoring candidates' },
  { at: 54, label: 'Almost ready', sub: 'Assembling your suggestions' },
];

// Charts: external chart providers only — no library/personalisation copy.
export const SUGGESTION_STAGES_CHARTS = [
  { at: 0, label: 'Connecting to sources', sub: 'Reaching the chart providers' },
  { at: 12, label: 'Fetching charts', sub: 'TheMovieDB · IMDb · Blu-ray'},
  { at: 26, label: 'Collecting titles', sub: 'Gathering ranked entries' },
  { at: 42, label: 'Building the list', sub: 'Sorting by popularity' },
  { at: 54, label: 'Almost ready', sub: 'Assembling the charts' },
];

// Default seconds before the loader switches to the "still working" state.
// INVARIANT: this must be >= the last stage's `at` (currently 54) so the whole
// staged narrative plays out before "Still working" takes over the heading.
// If it fired earlier, the stalled heading ("Still working") and the checklist
// (which keeps advancing with elapsed) would contradict each other once a later
// stage lit up. 60 also matches the "Usually 30–60s" reassurance copy: we only
// offer the Skip-to-Library recovery once you're at the edge of the usual window.
// (Guarded by a unit test in suggestion-loader.spec.ts.)
export const SUGGESTION_STALL_AFTER = 60;

// Seconds the stall timer is pushed back when the user clicks "Keep waiting" —
// the grace period before the loader stalls again. A peer of SUGGESTION_STALL_AFTER;
// kept here (named + unit-tested) so all loader timing lives in one tuneable place
// instead of as a bare literal in the Alpine controller.
export const SUGGESTION_KEEP_WAITING_EXTENSION = 30;

// The active stage for a given elapsed time: the last stage whose `at` threshold
// has been reached. Always returns a stage (defaults to the first).
export function suggestionStage(elapsed, stages = SUGGESTION_STAGES) {
  let current = stages[0];
  for (const stage of stages) {
    if (elapsed >= stage.at) current = stage;
  }
  return current;
}

// Progress percentage for the bar. Snaps to 100 once loaded; otherwise eases
// toward a 92% ceiling over ~60s so the bar always reads as moving but never
// claims "done" before the content actually arrives.
export function suggestionPct(elapsed, loaded) {
  if (loaded) return 100;
  return Math.min(92, Math.round((elapsed / 60) * 92));
}

// A checklist row `i` is "done" when the whole load has finished, or when the
// NEXT stage's threshold has been reached (i.e. we have moved past row `i`).
export function suggestionStageDone(i, elapsed, loaded, stages = SUGGESTION_STAGES) {
  if (loaded) return true;
  const next = stages[i + 1];
  return Boolean(next && elapsed >= next.at);
}

// A checklist row `i` is "current" when the load is still running and `i` is the
// active stage. Identity-compares against the array element suggestionStage
// returns, so both must read from the same `stages` reference.
export function suggestionStageCurrent(i, elapsed, loaded, stages = SUGGESTION_STAGES) {
  if (loaded) return false;
  return suggestionStage(elapsed, stages) === stages[i];
}
