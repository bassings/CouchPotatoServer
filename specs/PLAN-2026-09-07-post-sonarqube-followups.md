# PLAN: the work the SonarQube pass uncovered

The scanner pass closed on 2026-09-07 with 1267 open findings down to 1131 and
nothing dismissed to move a number. Its real output was four user-facing
defects that no rule reported, found by reading code while assessing findings
that mostly did not need fixing. This plan carries those, plus two pieces of
overdue hygiene the pass exposed.

Explicitly OUT OF SCOPE, by the owner's instruction: the seven merged library
records on the production server. Not touched by this plan.

## Tasks

- [ ] T1: production promotion. Fourteen commits have merged since v3.77.0 and
      none are in production, including BUG-018, where the scanner filed every
      remake under the original film, and the Docker CVE pin. The backup
      trigger is a mechanical test, and it says TAKE ONE: 47 non-exempt files
      have changed since the last stable tag. So `./scripts/backup.sh` first,
      verify the snapshot exists and is non-empty, then promote the tested
      beta byte-for-byte. Owner has agreed to THIS promotion; a later one for
      the fixes below needs its own agreement, state: queued
- [ ] T2: run `make sonar` automatically after a merge to master. The pass
      found this project had not been analysed since 2026-08-10, so every line
      number in the dashboard described a tree a month stale, and that nearly
      produced a dismissal justifying the wrong function. MUST NOT be a
      blocking gate and must never fail a build: the standards are explicit
      that a scan which can fail a build creates pressure to make the number
      green rather than the code better, state: queued
- [ ] T3: issue #312, event wiring is guarded in one direction only.
      `test_event_wiring.py` catches an event fired with no listener, and
      nothing catches a listener with no sender, which is the direction that
      has actually cost this project. 38 registered names are never fired.
      Deliverable is the reverse guard plus an adjudication of the 38, with an
      allowlist that fails in both directions so it cannot become a dumping
      ground. Confirmed dead so far: `movie.snatched` and `movie.downloaded`
      (no notification on grab or completion), `media.mark_watched`, and
      `app.test`, which has four listeners including a 12-case path-safety
      table for `isSubFolder` that has not run since the FastAPI migration,
      state: queued (needs: T1)
- [ ] T4: issue #311, the Trakt OAuth device flow has no reachable UI.
      `automation.trakt.device_code` and `automation.trakt.poll_token` are
      registered API views whose only caller is `trakt.js`, which nothing
      serves. Anyone configuring Trakt today cannot complete authorisation.
      Port the control into `couchpotato/ui/`, or retire the endpoints if the
      feature is not wanted, state: queued (needs: T3)
- [ ] T5: issue #314, the folder browser announces `role="listbox"` and keeps
      none of it: no arrow keys, no `aria-selected`, no
      `aria-activedescendant`, every folder its own tab stop. Remove the ARIA
      rather than adopt the `<select>` the scanner suggested. Fold in the
      known keyboard-escape and focus-trap gap in the same modal, and consider
      the eight deferred `Web:S6819` dialog findings here since a native
      `<dialog>` solves that half properly, state: queued (needs: T4)
- [ ] T6: five films identified earlier today that are still not added to the
      library. Data task, no PR, state: queued (needs: T5)

## Conductor log
