# UI-CONFORM-02 — CI conformance guardrail (Gap 4)

## Problem

Nothing fails a build when design-system drift sneaks into the modern UI. The
`accessibility` axe job exists but isn't a required status check, and there is no
static check for legacy classes / off-spec toggle sizes / raw hex colors. This
lets the regressions we just fixed (UI-CONFORM-01, UI-CLEANUP-01) creep back.

## Fix

Add a **fast static conformance check** that fails CI when the modern UI
(`couchpotato/ui/templates/**`) drifts, plus wire it into CI as a gating job.

1. Create `scripts/check_conformance.py` (pure stdlib, no new deps) that scans
   `couchpotato/ui/templates/**/*.html` and exits non-zero (printing each
   offending file:line) when it finds any of:
   - Off-spec toggle sizing: `w-10 h-5`, `translate-x-5` (the only sanctioned
     toggle is `w-8 h-4` / `w-3 h-3` / `translate-x-4`).
   - Legacy icon-font classes: a `class="..."` containing a `icon-` token
     (e.g. `icon-emo-coffee`, `icon-download`). Modern UI uses inline Heroicon
     SVGs.
   - Raw hex colors used as Tailwind arbitrary values or inline styles in the
     modern templates: hex inside `class="..."` (e.g. `bg-[#ff0000]`,
     `text-[#fff]`) or inside a `style="..."` attribute. Use `cp-*` tokens /
     CSS variables instead.
   IMPORTANT — avoid false positives: the check MUST PASS on the current
   (post-cleanup) tree. Do NOT flag legitimate token DEFINITIONS: the
   `tailwind.config` `<script>` block and the `:root`/`:root.light` `<style>`
   block in `base.html`, the `<meta name="theme-color" content="#...">` tag, or
   hex inside SVG `fill=`/`stroke=` attributes. Scope the hex rule to
   `class="..."` arbitrary values and `style="..."` declarations only. Tune it so
   the existing tree is clean; if a legitimate existing usage would trip it,
   narrow the rule rather than editing templates.
   Make the offending-pattern list and any file/line exclusions explicit and
   commented so it's maintainable.

2. Add a `conformance` job to `.github/workflows/ci.yml` that runs
   `python scripts/check_conformance.py` (Python 3.x, ubuntu-latest). Keep it
   fast (no build). Give it a clear job name/`id` so it reports a
   `conformance` status check.

3. Add `tests/unit/test_check_conformance.py`: assert the script passes on the
   real repo tree, and (using tmp fixtures / inline HTML strings) that it FAILS
   on each of the three drift patterns (a `w-10 h-5` toggle, an `icon-emo-coffee`
   class, a `class="bg-[#abcdef]"`), and PASSES on canonical equivalents
   (`w-8 h-4`, an inline `<svg>`, `bg-cp-accent`). TDD: write these first.

Do NOT change branch-protection settings — the orchestrator handles making
`accessibility` and `conformance` required checks separately.

## Acceptance criteria

- `python scripts/check_conformance.py` exits 0 on the current tree.
- The three positive-detection tests fail the script (non-zero) as designed.
- `ci.yml` has a `conformance` job invoking the script.
- `ruff check .` clean; `.venv/bin/python -m pytest tests/unit/ -q` passes.

## Files

- `scripts/check_conformance.py` (new)
- `.github/workflows/ci.yml` (new `conformance` job)
- `tests/unit/test_check_conformance.py` (new)
