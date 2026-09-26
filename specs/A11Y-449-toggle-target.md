# A11Y-449: Verify toggle target size

## Problem

The sanctioned switch track is 32 × 16 CSS pixels. WCAG 2.2 AA 2.5.8
requires a 24 × 24 CSS pixel target, or sufficient spacing for an undersized
target's centred 24 CSS pixel circle. The current templates do not establish
which exception, if any, applies to each rendered switch.

This follows `specs/UI-CONFORM-01-toggle-normalize.md`. The visual switch size
and its existing state, keyboard and contrast behaviour should remain stable
unless measurement shows a change is needed.

## Acceptance criteria

- At desktop and phone widths, a browser test reaches every switch family:
  settings header, provider card, combined-row `use`, and the wizard partial
  across provider, expanded private-tracker, downloader and library steps. A
  missing expected family fails the test.
- For each visible switch, measure its rendered target and adjacent pointer
  targets. If either dimension is under 24 CSS pixels, verify that a centred
  24 CSS pixel circle intersects neither another target nor another undersized
  target's circle. Follow the W3C's [SC 2.5.8 spacing definition](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum).
- A deliberately crowded undersized switch fails the new check, and restoring
  its spacing makes the check pass. Keep test setup isolated from persisted
  settings and assert the expected controls actually rendered.
- If any real switch fails, enlarge its pointer target or spacing with the
  smallest visual change, then rerun the browser measurement in both themes.
  Preserve the switch's ARIA state, keyboard operation, focus visibility and
  existing contrast checks. The provider-card header has its own collapse
  action, so its nested switch needs a full 24px pointer height while keeping
  the painted track at 16px.
- Run focused Playwright checks, the relevant conformance gate and the full
  repository gate before delivery. Obtain two independent local reviews before
  any push.
