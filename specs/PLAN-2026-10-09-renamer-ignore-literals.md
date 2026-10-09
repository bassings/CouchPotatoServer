# SonarQube renamer ignore marker literals, 2026-10-09

## Finding

The exact clean-master scan at `d76f31e1` reports two critical `python:S1192`
repeated literals in `couchpotato/core/plugins/renamer/cleanup.py`: the
`.ignore` extension and the `%s.%s.ignore` tag filename pattern. These values
participate in creating, detecting and removing tag files, and in deciding
whether a source folder may be deleted. The renamer handles downloaded media,
so literal extraction must preserve file safety at each boundary.

## Acceptance criteria

1. Share both exact values within the module without changing tag paths,
   ignore-file recognition, untag behaviour or folder-deletion decisions.
2. Characterise tag, untag, detection and deletion against real temporary
   files. Include a boundary where an ordinary media file prevents deletion.
   Prove new tests are load-bearing with deliberate source mutations and
   restoration. After inlining constants, the module syntax tree matches the
   pre-change source.
3. A fresh coverage report covers at least 80% of changed executable lines.
   Focused tests, the full repository gate and two independent local reviews
   pass before push.
4. PR, CI and cloud review pass; a clean-master scan closes both targeted
   issue keys, adds no issues and passes the reporting quality gate. No
   production deployment.

## Tasks

- [x] I1 Add real-file characterisation and mutation proof; state: completed
- [x] I2 Extract exact literals and verify syntax-tree equivalence and coverage; state: completed
- [ ] I3 Complete gates, reviews, PR, merge and exact-master scan; state: queued

## Conductor log

- 2026-10-09: Selected the two renamer ignore-literal findings from the seven
  low-coverage critical literals held out of the broader batch. Existing
  full-suite coverage marks seven affected executable lines uncovered, so
  file-boundary tests are required before this extraction can meet the new
  coverage gate.
- 2026-10-09: Two real-file tests passed on the original source and after
  exact literal extraction. They exercise all seven previously uncovered
  affected lines, including protection of an ordinary media file during
  folder cleanup. Wrong extension and wrong tag-pattern mutations each made
  the tests fail; restoration passed. Inlining the two constants yields the
  original module syntax tree.
- 2026-10-09: Fresh `make coverage` passed with 4,915 Python tests and covered
  all nine changed executable lines in the renamer module. Full verification
  and independent reviews remain pending.
