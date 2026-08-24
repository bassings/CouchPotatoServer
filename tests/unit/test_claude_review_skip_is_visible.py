"""`claude-review` is a REQUIRED check that can pass without running.

`anthropics/claude-code-action` refuses to act when the workflow file it runs
from differs from the copy on the default branch, logging "Skipping action due
to workflow validation" and exiting quietly. GitHub itself RUNS the workflow --
every step of run 32337224625 on #281 reports success -- so the required
`claude-review` check goes green with no review behind it.

That distinction matters and this file had it wrong at first: the guard tracks a
THIRD-PARTY ACTION'S self-check, pinned to a floating `@v1` tag, not a platform
invariant. Anthropic can change the condition, the message or its scope in any
release and nothing here would notice. These tests pin our side of it.

Measured, four for four: #129, #132, #149 and #281 each edit this file and each
carries ZERO `claude[bot]` comments, while every non-Dependabot PR around them
has them. ALL FOUR were themselves changes to the reviewer -- a visible verdict,
comment permissions, the Dependabot skip, and finding routing -- so the changes
least able to afford going unreviewed are exactly the ones that did. The reason
appears in the job log a few hundred lines in, where nobody looks.

WHY THIS FILE EXECUTES THE STEP INSTEAD OF READING IT

The first two versions of this file asserted on the TEXT of the workflow: does
it contain `gh pr comment`, does it mention the default branch. Adversarial
review found FOURTEEN mutations that left every one of those assertions green,
five of which permanently deadlock the workflow, and one of which made the step
announce the exact opposite of the truth by changing a single token
(`origin/$DEFAULT_BRANCH` -> `HEAD`). Two earlier rounds each fixed one instance
and missed the class: a substring grep is the wrong instrument for pinning shell
BEHAVIOUR, and no amount of tightening the greps changes that.

So the important tests here extract the step's `run:` body from the YAML and
EXECUTE it against a real throwaway git repository with a stubbed `gh`, then
assert on what actually happened: the exit status, what was printed, and whether
a comment was posted. Every one of those fourteen mutations is red against this,
because none of them survives being run.

The YAML-shape tests that remain guard what execution cannot see: that the step
exists at all, that it is wired to run when the action above it was skipped, and
that the job still has the name branch protection requires.

WHY THE STEP MUST NOT FAIL THE JOB

Failing deadlocks the workflow permanently: the only way to repair the file
would be a PR that the gate now blocks. A skipped review must be VISIBLE, not
BLOCKING. Every behavioural test below asserts exit 0 for that reason, including
the paths where the step cannot determine an answer.

KNOWN LIMITS, stated because a guard whose blind spot is undocumented is worse
than one with a narrow scope:

- These tests prove the step's shell behaves correctly. They cannot prove
  GitHub's runners invoke it, nor that GitHub still skips workflows for this
  reason. The behavioural half is proven by the PR that introduces this, which
  edits this very workflow and must therefore trigger the skip it detects.
- A fork or Dependabot pull request may run with a read-only `GITHUB_TOKEN`, in
  which case `gh pr comment` fails with 403 and the notice degrades to the
  `::warning::`, which GitHub renders as a check-run ANNOTATION on
  claude-review. The annotation is the guaranteed half; the comment is the
  convenience. The stubbed `gh` here always succeeds, so no test covers the
  403 path.

  (This limit used to read "step-level `if: always()` does not override the
  JOB-level `if:`, so fork and Dependabot PRs are not covered". That was true
  and is now the opposite of true: the exclusion was moved onto the review step
  precisely so the job always runs, and `test_the_job_itself_is_not_conditional`
  below exists to stop anyone putting it back. Left here as a correction rather
  than deleted, because a stale known-limit is how someone re-opens a closed
  hole while believing they are fixing it.)
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.conftest import sanitized_git_env

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / '.github' / 'workflows' / 'claude-review.yml'
SELF_PATH = '.github/workflows/claude-review.yml'


def _q(path):
    """Single-quote a path for the shell stub."""
    return "'" + str(path).replace("'", "'\\''") + "'"


def _job():
    assert WORKFLOW.is_file(), f'workflow not found at {WORKFLOW}'
    doc = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    job = (doc.get('jobs') or {}).get('claude-review')
    assert job, (
        "no `claude-review` job in the workflow. If it was renamed, the required "
        "status check on master was renamed with it -- update this test WITH the file"
    )
    return job


def _detection_step():
    """The step that must run even when the action above it was skipped.

    Matched on the `if` expression CONTAINING always(), not equalling it:
    `if: ${{ always() }}` and `if: always() && <cond>` are both legal GitHub and
    both were false failures under an equality match.
    """
    steps = [s for s in (_job().get('steps') or []) if 'always()' in str(s.get('if', ''))]
    assert len(steps) == 1, (
        'expected exactly one step whose `if:` contains always() in %s, found %d. '
        'That step is the skip detection: without it nothing executes on a run '
        'GitHub skipped by workflow validation, so the required check reports '
        'success with no review and no trace. Four PRs have already passed that '
        'way' % (SELF_PATH, len(steps))
    )
    return steps[0]


def _git(*args, cwd):
    """Fixture git, and it must be loud.

    Every call site used to discard the return code. Review dropped just the
    `git push` from the fixture and eight of ten tests still passed, because the
    two negative tests assert `body is None` -- which any broken fixture
    satisfies. A silent fixture failure turns a behavioural test into a test of
    nothing, so this raises instead.
    """
    proc = subprocess.run(
        ['git', *args], cwd=str(cwd), env=sanitized_git_env(),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        'fixture setup failed: git %s -> %d\n%s%s'
        % (' '.join(args), proc.returncode, proc.stdout, proc.stderr)
    )
    return proc


def _step_env():
    """The step's declared `env:`, with GitHub-supplied expressions resolved.

    Literal values -- notably SELF, the path the guard watches -- are taken
    from the workflow ITSELF rather than supplied by the test. Review changed
    SELF to `.github/workflows/ci.yml`, which disables the guard permanently,
    and the earlier harness passed because it overrode SELF with the value it
    wanted. A test that supplies the thing under test proves nothing.
    """
    declared = (_detection_step().get('env') or {})
    for required in ('PR_NUMBER', 'DEFAULT_BRANCH', 'SELF', 'REVIEW_OUTCOME'):
        assert required in declared, (
            '%s is not declared in the detection step\'s env. The shell reads '
            'it, so deleting the declaration changes behaviour -- and under '
            '`set -u` an undeclared variable exits 1, which fails a REQUIRED '
            'check and deadlocks every future edit to this workflow' % required
        )
    # REVIEW_OUTCOME reads `steps.<id>.outcome`. That <id> is a REPO-INTERNAL
    # binding, not something GitHub supplies, so it must be checked against the
    # workflow the way SELF is. Review renamed `id: review` to `id: reviewer`
    # and all ten tests stayed green while the expression silently resolved to
    # an empty string, deleting the fork/Dependabot branch entirely.
    ref = str(declared['REVIEW_OUTCOME'])
    m = re.search(r'steps\.([A-Za-z0-9_-]+)\.outcome', ref)
    assert m, (
        'REVIEW_OUTCOME does not read a step outcome (%r). The detection needs '
        'to know whether the review step actually ran' % ref
    )
    review = [
        s for s in (_job().get('steps') or [])
        if 'claude-code-action' in str(s.get('uses', ''))
    ]
    assert len(review) == 1, 'expected one claude-code-action step, got %d' % len(review)
    assert review[0].get('id') == m.group(1), (
        'REVIEW_OUTCOME reads steps.%s.outcome but the review step\'s id is %r. '
        'The expression resolves to an empty string, so the step reports that '
        'the review RAN on every fork and Dependabot pull request -- the exact '
        'population this branch exists to cover'
        % (m.group(1), review[0].get('id'))
    )
    supplied = {
        'PR_NUMBER': '4242',
        'DEFAULT_BRANCH': 'main',
        'REVIEW_OUTCOME': 'success',
    }
    out = {}
    for key, value in declared.items():
        text = str(value)
        # `${{ ... }}` is filled in by GitHub at run time; anything else is a
        # literal the workflow chose, and must be used as written.
        out[key] = supplied.get(key, '') if '${{' in text else text
    return out


def _drive_step(tmp_path, state, review_outcome='success', runs=1,
                foreign_marker=False):
    """Execute the detection step's shell against a real repo.

    `state`: 'same' (workflow matches the default branch), 'differs' (this PR
    edited it), 'new' (absent from the default branch), 'unfetchable'.
    `runs` executes the step that many times against the SAME pull request,
    so the duplicate-notice guard is tested end to end rather than by seeding
    a marker the test wrote itself.

    Returns (exit_code, output, gh_body, posts).
    """
    run = str(_detection_step().get('run', ''))
    assert run.strip(), 'the detection step has no shell to run'

    env = sanitized_git_env()
    env.update(_step_env())
    env['REVIEW_OUTCOME'] = review_outcome
    if state == 'unfetchable':
        env['DEFAULT_BRANCH'] = 'no-such-branch'
    watched = env['SELF']

    origin = tmp_path / 'origin.git'
    work = tmp_path / 'work'
    _git('init', '-q', '--bare', str(origin), cwd=tmp_path)
    _git('clone', '-q', str(origin), str(work), cwd=tmp_path)
    _git('config', 'user.email', 't@example.com', cwd=work)
    _git('config', 'user.name', 'T', cwd=work)

    # The repo always contains the REAL workflow path. `watched` is whatever the
    # step says it watches, so pointing it elsewhere makes the guard blind and
    # the tests notice.
    real = work / SELF_PATH
    real.parent.mkdir(parents=True, exist_ok=True)
    if state != 'new':
        real.write_text('name: baseline\n', encoding='utf-8')
    else:
        (work / 'unrelated.txt').write_text('x\n', encoding='utf-8')
    _git('add', '-A', cwd=work)
    _git('commit', '-q', '-m', 'baseline', cwd=work)
    _git('branch', '-M', 'main', cwd=work)
    _git('push', '-q', '-u', 'origin', 'main', cwd=work)

    if state in ('differs', 'new'):
        real.write_text('name: edited by this PR\n', encoding='utf-8')
        _git('add', '-A', cwd=work)
        _git('commit', '-q', '-m', 'edit the workflow', cwd=work)

    bindir = tmp_path / 'bin'
    bindir.mkdir()
    record = tmp_path / 'gh-body.txt'
    thread = tmp_path / 'pr-comments.txt'
    # Each line is '<author>\t<body>'. The stub honours the step's --jq
    # author filter, so a marker posted by someone else is distinguishable
    # from one we posted -- which is the whole point of the filter.
    seed = 'someone-else\tunrelated chatter\n'
    if foreign_marker:
        seed += 'someone-else\t<!-- claude-review-did-not-run --> spoofed\n'
    thread.write_text(seed, encoding='utf-8')
    posted = tmp_path / 'post-count.txt'
    shim = bindir / 'gh'
    # A stub that ACCUMULATES. The previous one served a hardcoded marker to
    # the duplicate check, so it proved the READER worked and never the
    # WRITER: deleting the marker from the posted body left every test green
    # while production went back to one notice per push. Here a post lands in
    # the same thread the next `pr view` reads, so the round trip is real.
    shim_src = '\n'.join([
        '#!/bin/sh',
        'if [ "${1:-}" = "pr" ] && [ "${2:-}" = "view" ]; then',
        '  if printf "%s\\n" "$@" | grep -q "select(.author.login"; then',
        '    grep "^github-actions\t" %s | cut -f2-' % _q(thread),
        '  else',
        '    cut -f2- %s' % _q(thread),
        '  fi',
        '  exit 0',
        'fi',
        'while [ $# -gt 0 ]; do',
        '  if [ "$1" = "--body" ]; then',
        '    printf %%s "$2" > %s' % _q(record),
        '    printf "github-actions\\t%%s\\n" "$2" >> %s' % _q(thread),
        '    printf x >> %s' % _q(posted),
        '  fi',
        '  shift',
        'done',
        'exit 0',
        '',
    ])
    shim.write_text(shim_src, encoding='utf-8')
    shim.chmod(0o755)

    env['PATH'] = str(bindir) + os.pathsep + env.get('PATH', '')
    env['GH_TOKEN'] = 'stub-token-not-a-real-credential'

    # `bash -e`, because that is GitHub's documented default shell for a `run:`
    # step on Linux (`bash -e {0}`), and a harness more forgiving than production
    # is a false green. This was NOT theoretical: an earlier version invoked
    # `sh`, which is bash on macOS and busybox in this repo's Alpine test image
    # -- both accept `set -o pipefail` -- but dash on ubuntu-latest, which
    # rejects it outright ("Illegal option -o pipefail", exit 2). Six of these
    # tests would have failed on the first push while every local gate stayed
    # green. --noprofile/--norc so a developer's shell config cannot change the
    # result.
    out = ''
    for _ in range(runs):
        proc = subprocess.run(
            ['bash', '--noprofile', '--norc', '-e', '-c', run],
            cwd=str(work), env=env, capture_output=True, text=True,
        )
        out += proc.stdout + proc.stderr
    body = record.read_text(encoding='utf-8') if record.exists() else None
    count = len(posted.read_text(encoding='utf-8')) if posted.exists() else 0
    return proc.returncode, out, body, count


needs_git = pytest.mark.skipif(
    shutil.which('git') is None or shutil.which('sh') is None,
    reason='needs git and sh to drive the step',
)


class TestTheStepExistsAndIsWired:
    """Shape, not behaviour: what executing the step cannot tell us."""

    def test_the_workflow_still_runs_the_review_action(self):
        uses = ' '.join(str(s.get('uses', '')) for s in (_job().get('steps') or []))
        assert 'claude-code-action' in uses, (
            'this workflow no longer runs claude-code-action; update this test '
            'WITH the file it guards'
        )

    def test_exactly_one_step_runs_when_the_action_was_skipped(self):
        assert _detection_step() is not None

    def test_the_job_itself_is_not_conditional(self):
        """A job skipped by a JOB-level `if:` runs ZERO steps, `if: always()`
        ones included. Measured on run 31556193805: conclusion "skipped",
        steps 0.

        The fork and Dependabot exclusion therefore belongs on the review STEP,
        never on the job. With it on the job the detection below can never fire
        for a fork or Dependabot pull request -- and dependabot.yml watches the
        github-actions ecosystem weekly, so Dependabot will open pull requests
        bumping `anthropics/claude-code-action` itself: a supply-chain change to
        the reviewer, merging on a green required check with nobody told.

        This is the one regression the behavioural tests cannot see, because
        they execute the step's shell and the shell is fine. Only the job's
        shape says whether it ever runs."""
        job = _job()
        assert 'needs' not in job, (
            'the claude-review job has `needs: %r`. A job whose dependency is '
            'skipped is itself skipped, running zero steps -- so folding the '
            'fork/Dependabot condition into a shared gate job re-opens exactly '
            'the hole this test exists to close, by a different route'
            % (job.get('needs'),)
        )
        assert 'strategy' not in job, (
            'the claude-review job has a `strategy:`. A matrix that expands to '
            'zero combinations runs zero steps, which is the same hole again'
        )
        job_if = job.get('if')
        assert not job_if, (
            'the claude-review JOB has a top-level `if:` (%r). A skipped job '
            'runs no steps at all, so the skip-detection step cannot fire for '
            'whichever pull requests this excludes -- and those are exactly the '
            'ones nobody reviews. Put the condition on the review STEP instead: '
            'the job then always runs, still reports a green required check, '
            'and the detection always fires' % job_if
        )

    def test_the_review_step_carries_the_fork_and_bot_exclusion(self):
        """Guards the other direction: moving the condition to the step is only
        safe if it is actually THERE. Dropping it entirely would run the
        reviewer on fork pull requests with this repo's token."""
        steps = _job().get('steps') or []
        review = [s for s in steps if 'claude-code-action' in str(s.get('uses', ''))]
        assert len(review) == 1, 'expected one claude-code-action step, got %d' % len(review)
        cond = str(review[0].get('if', ''))
        # Substring presence is not enough: review inverted the whole condition
        # to `!= repository || actor == dependabot` -- which runs the reviewer
        # ONLY on forks and Dependabot -- and both substrings survived, so the
        # earlier version of this assertion passed. Check the operators.
        assert 'head.repo.full_name == github.repository' in cond, (
            'the review step no longer excludes fork and Dependabot pull '
            'requests with the right sense (`if:` is %r). That condition was '
            'moved here from the job deliberately; losing or inverting it would '
            'run the reviewer on untrusted fork pull requests' % cond
        )
        assert "github.actor != 'dependabot[bot]'" in cond, (
            'the review step no longer excludes Dependabot with the right sense '
            '(`if:` is %r)' % cond
        )
        assert '||' not in cond, (
            'the exclusion is joined with `||` (`if:` is %r), which widens it '
            'rather than narrowing it. Both clauses must hold' % cond
        )


@needs_git
class TestTheStepBehavesWhenRun:
    """The tests that matter. Fourteen mutations survived text assertions; none
    survives execution."""

    @staticmethod
    def _assert_says_no_review_happened(body):
        low = body.lower()
        assert 'did not run' in low or 'skip' in low, (
            'the notice never says the review did not happen, so it reads like '
            'any other automated comment. Body:\n%s' % body
        )
        assert 'green' in low and ('not' in low or 'does not' in low), (
            'the notice does not tell the reader that the green check is not a '
            'passed review, which is the single thing it exists to say. '
            'Body:\n%s' % body
        )
        assert 'other means' in low, (
            'the notice does not tell the reader what to DO. Body:\n%s' % body
        )

    def test_a_validation_skip_is_announced_and_posted(self, tmp_path):
        code, out, body, posts = _drive_step(tmp_path, 'differs')
        assert code == 0, (
            'exited %d on a workflow-editing PR. Any non-zero exit fails a '
            'REQUIRED check, which deadlocks every future edit to this '
            'workflow: the only PR that could repair it would be blocked by '
            'this gate. Output:\n%s' % (code, out)
        )
        assert 'SKIP' in out.upper(), 'nothing logged about a skip:\n%s' % out
        assert body is not None, (
            'no comment posted for a skipped review. The job log already carries '
            'the reason a few hundred lines in, where nobody looks -- that is the '
            'status quo this step exists to change'
        )
        self._assert_says_no_review_happened(body)

    def test_the_step_being_skipped_by_its_own_gate_is_also_reported(self, tmp_path):
        """The population that matters most. dependabot.yml watches the
        github-actions ecosystem weekly, so Dependabot will open PRs bumping
        `anthropics/claude-code-action` -- changing the reviewer itself, on a PR
        the reviewer does not review."""
        code, out, body, posts = _drive_step(
            tmp_path, 'same', review_outcome='skipped',
        )
        assert code == 0, 'exited %d:\n%s' % (code, out)
        assert body is not None, (
            'the review step was skipped by its own condition (fork or '
            'Dependabot) and NOTHING was reported. The workflow file matches the '
            'default branch, so the validation check stays silent -- if this path '
            'is not covered, those PRs get a green required check, no review, and '
            'no notice'
        )
        self._assert_says_no_review_happened(body)
        assert 'dependabot' in body.lower() or 'fork' in body.lower(), (
            'the notice does not say WHY the review did not run, so the reader '
            'cannot tell this from a validation skip. Body:\n%s' % body
        )

    def test_an_ordinary_pull_request_posts_nothing(self, tmp_path):
        code, out, body, posts = _drive_step(tmp_path, 'same')
        assert code == 0, 'exited %d on an ordinary PR:\n%s' % (code, out)
        assert body is None, (
            'a notice was posted on a PR where the review DID run. Every clean '
            'PR would carry a false warning, which trains people to scroll past '
            'the real one. Body:\n%s' % body
        )
        # `body is None` alone is satisfied by ANY broken fixture, so assert the
        # step actually reached its decision. Review proved the point by dropping
        # the fixture's `git push`: eight of ten tests still passed.
        assert 'not skipped' in out.lower() or 'matches' in out.lower(), (
            'the step did not report reaching the "review ran normally" '
            'conclusion, so `body is None` may mean the fixture broke rather '
            'than that the step decided correctly. Output:\n%s' % out
        )

    def test_a_workflow_absent_from_the_default_branch_is_reported(self, tmp_path):
        """A brand-new workflow is not on the default branch at all, and the
        action skips that case too ("must EXIST and have identical content"), so
        silence would be wrong."""
        code, out, body, posts = _drive_step(tmp_path, 'new')
        assert code == 0, 'exited %d for a new workflow:\n%s' % (code, out)
        assert body is not None, (
            'a workflow absent from the default branch posted no notice'
        )

    def test_the_notice_is_posted_once_per_pull_request_not_once_per_push(self, tmp_path):
        """The reviewer's own summaries show the failure mode: #277 and #279 each
        accumulated five comments. Repeating the one notice that must not be
        ignored is how it gets ignored."""
        code, out, body, posts = _drive_step(tmp_path, 'differs', runs=3)
        assert code == 0, 'exited %d:\n%s' % (code, out)
        assert posts == 1, (
            'the step ran three times (three pushes to one pull request) and '
            'posted %d notices. It must post once. This drives the real round '
            'trip -- what the step posts is what the duplicate check later '
            'reads -- so it also fails if the marker is dropped from the body, '
            'which the earlier seeded fixture could not detect' % posts
        )

    def test_a_marker_posted_by_someone_else_does_not_suppress_the_notice(self, tmp_path):
        """The marker is an HTML comment, so it renders as nothing, and this
        repo is public. Anyone able to comment could otherwise post it once and
        silence this notice permanently and invisibly. The accidental path is
        likelier than the malicious one: quoting this workflow's source in a
        comment plants it, and the reviewer itself quotes diffs of this file."""
        code, out, body, posts = _drive_step(
            tmp_path, 'differs', foreign_marker=True,
        )
        assert code == 0, 'exited %d:\n%s' % (code, out)
        assert posts == 1, (
            'the notice was suppressed by a marker in someone ELSE\'s comment '
            '(posted %d times). The duplicate check must only trust comments we '
            'posted ourselves, or anyone who can comment can silence it' % posts
        )

    def test_an_unresolvable_outcome_is_reported_not_assumed_successful(self, tmp_path):
        """`steps.<id>.outcome` resolves to an empty string if the id no longer
        matches -- a one-word rename. Testing for `!= success` rather than
        `= skipped` makes that fail SAFE: an unexpected value reports rather
        than stays quiet. Review measured the alternative, where an empty value
        made the step affirmatively state the review had run."""
        for outcome in ('', 'failure', 'cancelled'):
            sub = tmp_path / (outcome or 'unresolved')
            sub.mkdir()
            code, out, body, posts = _drive_step(
                sub, 'same', review_outcome=outcome,
            )
            assert code == 0, 'exited %d for outcome %r:\n%s' % (code, outcome, out)
            assert posts == 1, (
                'outcome %r produced %d notices. Anything other than a '
                'successful review means no review happened, and must be '
                'reported rather than assumed fine' % (outcome, posts)
            )

    def test_an_unknown_answer_says_so_and_does_not_claim_success(self, tmp_path):
        code, out, body, posts = _drive_step(tmp_path, 'unfetchable')
        assert code == 0, (
            'exited %d when the default branch could not be fetched. An '
            'environmental failure must not fail a required check:\n%s' % (code, out)
        )
        low = out.lower()
        assert 'unknown' in low or 'unproven' in low, (
            'when it cannot tell whether the review ran, the step must SAY so. '
            'Silence is indistinguishable from "the review ran", which is the '
            'defect this file exists to remove. Output:\n%s' % out
        )
        assert 'was not skipped' not in low, (
            'claimed the review was not skipped when it could not determine '
            'that. Output:\n%s' % out
        )
