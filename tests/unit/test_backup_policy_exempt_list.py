"""The backup policy's exempt list must exist in exactly one form.

This file exists because prose failed three times on a single change. The
policy is stated in `scripts/backup.sh`'s header and mirrored in
`docs/development-process.md`, and within three commits of being written the
two copies had already diverged twice and `CLAUDE.md` had grown a third
paraphrase:

    round 1  backup.sh exempted "pure-presentation assets with no script in
             them"; the doc did not
    round 2  backup.sh exempted "lint or formatter config that does not ship
             in the image", an EMPTY category (ruff's config is in
             pyproject.toml and the Dockerfile ships the whole tree)
    round 3  CLAUDE.md compressed the list to "docs, tests or CI config"

Every one was caught by a reviewer reading carefully, which is exactly the
thing that does not scale. Per this project's standard, a rule that can be a
check should be a check: a weaker reader forgets prose, and cannot get past a
command that exits non-zero.

The guard is deliberately about AGREEMENT, not about the list's content. It
does not care what the exempt set is, only that there is one of it. Changing
the policy means changing both copies in the same commit, which is the whole
point.
"""
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKUP_SH = ROOT / 'scripts' / 'backup.sh'
DEV_PROCESS = ROOT / 'docs' / 'development-process.md'
CLAUDE_MD = ROOT / 'CLAUDE.md'

#: The paths the policy exempts, as they appear in both copies. Backticked so
#: an accidental prose mention ("see docs/") cannot masquerade as an entry.
_ENTRY = re.compile(r'`([^`]+)`')


def _exempt_entries(text, marker):
    """The backticked paths on the `Exempt:` line of `text`.

    Anchored on the marker line and its continuations rather than a fixed line
    range: a hardcoded range silently desyncs the moment the surrounding
    comment block changes length, which is the same defect `usage()` in
    backup.sh already carries a note about.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if marker in line:
            block = [line]
            # Continuations: subsequent lines in the same comment or quote that
            # are not blank once their prefix is stripped.
            for nxt in lines[i + 1:]:
                stripped = nxt.lstrip('#> ').strip()
                if not stripped:
                    break
                block.append(nxt)
            return _ENTRY.findall(' '.join(block))
    return []


@pytest.fixture(scope='module')
def lists():
    sh = _exempt_entries(BACKUP_SH.read_text(encoding='utf-8'), 'Exempt:')
    doc = _exempt_entries(DEV_PROCESS.read_text(encoding='utf-8'), 'Exempt:')
    return sh, doc


class TestTheTwoCopiesAgree:

    def test_the_sweep_found_a_real_list_in_both(self, lists):
        """The vacuity guard, and it is not decoration.

        If either extraction returns nothing, the equality assertion below
        compares two empty lists and passes for ever while the copies drift
        freely. That is the exact shape this repo has been bitten by more than
        once: a guard whose coverage metric agrees with it right up until it
        stops looking.
        """
        sh, doc = lists
        assert len(sh) >= 4, (
            f'only {len(sh)} exempt entries found in scripts/backup.sh -- the '
            f'extraction has stopped seeing the list, so the comparison below '
            f'cannot fail: {sh}'
        )
        assert len(doc) >= 4, (
            f'only {len(doc)} exempt entries found in '
            f'docs/development-process.md -- see above: {doc}'
        )

    def test_the_exempt_lists_are_identical(self, lists):
        sh, doc = lists
        assert sh == doc, (
            'the backup policy\'s exempt list has drifted between its two '
            'copies:\n'
            f'  scripts/backup.sh          {sh}\n'
            f'  docs/development-process.md {doc}\n'
            'Change both in the same commit. If you are adding a category, '
            'check first that it names anything real and that applying it '
            'needs no judgement -- two proposed categories have already '
            'failed one or both of those tests.'
        )


#: A line that states the rule: "take it unless ... changed ...". Any such
#: line must DEFER to the exempt list rather than enumerate it inline.
_RULE_LINE = re.compile(r'unless\b.*\bchang', re.I)

#: Words that mean someone has started enumerating the exempt set in prose.
#: Deliberately crude: the point is to catch a paraphrase forming, not to
#: validate its contents.
_ENUMERATION = re.compile(r'\b(docs|tests|specs|CI config|config)\b\s*,', re.I)


class TestNoFileRestatesTheRuleInPassing:
    """The blind spot in the first version of this guard, found by review and
    recorded because the shape matters more than the instance.

    That version compared the two `Exempt:` lines and nothing else. It was
    therefore blind to every RESTATEMENT elsewhere in the same files, and two
    survived it in the copies an operator is most likely to read: `usage()`'s
    heredoc in backup.sh, and the deploy runbook's step 1. Both said "docs,
    tests or CI config", which silently drops `specs/` and compresses
    `.github/`, so a promotion touching only `specs/` was exempt under the
    canonical list and ambiguous under the paraphrase.

    A guard that pins the canonical statement while ignoring every copy of it
    is the same failure this project keeps finding elsewhere: it looks like
    protection, it passes, and the thing it was built to prevent walks past it.

    So the rule is now structural. Anywhere these files state the trigger, the
    sentence must point at the exempt list instead of listing it again. There
    is one place the list appears, and everywhere else defers to it.
    """

    @pytest.mark.parametrize('path', [BACKUP_SH, DEV_PROCESS, CLAUDE_MD],
                             ids=lambda p: p.name)
    def test_every_statement_of_the_rule_defers_to_the_list(self, path):
        offenders = []
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not _RULE_LINE.search(line):
                continue
            # The canonical statement is the one that hands off to the list.
            if 'exempt' in line.lower():
                continue
            if _ENUMERATION.search(line):
                offenders.append(f'{path.name}:{n}: {line.strip()}')
        assert not offenders, (
            'the backup trigger is restated with an inline enumeration '
            'instead of deferring to the exempt list:\n  '
            + '\n  '.join(offenders)
            + '\n\nSay "in the exempt list" and point at it. Every inline '
            'copy is another thing to drift, and two of them already did.'
        )

    def test_the_rule_is_actually_stated_somewhere(self):
        """Vacuity guard. If the regex stops matching the rule at all, the
        test above iterates over nothing and passes for ever."""
        found = [
            p.name for p in (BACKUP_SH, DEV_PROCESS)
            if any(_RULE_LINE.search(l)
                   for l in p.read_text(encoding='utf-8').splitlines())
        ]
        assert len(found) == 2, (
            f'the rule statement was found in {found} but expected both files '
            f'-- the pattern has stopped matching, so the check above is inert'
        )


class TestNobodyElseRestatesIt:
    """`CLAUDE.md` grew a third, compressed paraphrase and nobody noticed
    until review. A pointer cannot drift; a copy can."""

    def test_claude_md_points_rather_than_paraphrases(self):
        row = [
            line for line in CLAUDE_MD.read_text(encoding='utf-8').splitlines()
            if 'scripts/backup.sh' in line and line.lstrip().startswith('|')
        ]
        assert row, 'the backup.sh row vanished from CLAUDE.md\'s command table'
        assert len(row) == 1, f'more than one backup.sh row: {row}'
        assert 'scripts/backup.sh`\'s header' in row[0] or 'header' in row[0], (
            'CLAUDE.md\'s backup.sh row no longer points at the canonical '
            'statement of the exempt list. Point at it; do not restate it. '
            'A third copy is a third thing to drift, which is how this row '
            'came to say "docs, tests or CI config" while the real list said '
            'something else.'
        )
