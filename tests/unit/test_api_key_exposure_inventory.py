"""Where the api_key still reaches the browser, written down. AC-SEC-47, D7.

The separation this PR builds is ONE-WAY. The browser's session cookie stops
being the api_key, so a stolen cookie is no longer full API access and signing
out actually revokes. What did not change is that every rendered page still
carries the api_key in `window.CP.apiBase`, because the new UI's Alpine and
htmx calls go to `/api/<key>/...` and re-authenticating those is a different
PR. So anyone who can read one page still has the key.

That is a real, accepted residue, and the failure mode is not the residue -- it
is the residue quietly growing. This file is the same shape as `PUBLIC_ROUTES`
in `test_route_auth_inventory.py`, and for the same reason: "the api_key goes
here" should be something a person has to write down and justify, not something
that happens because a template needed a URL.

The detector is deliberately narrow and mechanical:

  * a non-comment line reading `Env.setting('api_key')` in any shipped Python
    file under `couchpotato/`;
  * a template rendering `{{ api_key }}` or `{{ api_base }}`, `api_base` being
    the api_key with a path around it.

Both were measured before the allowlist was written, not guessed at.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / 'couchpotato'

#: path -> (number of matches, why this one is allowed to exist).
#:
#: A NEW path fails. A new match INSIDE an allowed path fails too, because the
#: count is pinned: `base.html` already renders the key once, and the next
#: template that wants it should be a decision rather than a diff nobody read.
#:
#: Counts are stable under ordinary editing -- they only move when somebody
#: adds or removes a place the key is used.
API_KEY_EXPOSURES = {
    # --- Reaches the browser. This is the residue D7 accepts and states. ---
    'couchpotato/ui/__init__.py': (
        1,
        'REACHES THE BROWSER. `_ctx` reads the api_key and puts it in every '
        'template context as `api_base`. Removing it means re-authenticating '
        'every Alpine fetch and htmx call in the new UI, which is a separate '
        'PR; D7 accepts it and states it in the PR body.',
    ),
    'couchpotato/ui/templates/base.html': (
        1,
        'REACHES THE BROWSER, and is the one that matters: `window.CP.apiBase` '
        'is rendered into every authenticated page, so reading any page yields '
        'the key. This is why the session cookie no longer BEING the key is a '
        'one-way separation rather than a fix.',
    ),
    'couchpotato/ui/templates/collections.html': (
        1, 'REACHES THE BROWSER via an `hx-get` to `{{ api_base }}`.'),
    'couchpotato/ui/templates/partials/collections.html': (
        1, 'REACHES THE BROWSER via an `hx-get` to `{{ api_base }}`.'),
    'couchpotato/ui/templates/partials/movie_collections.html': (
        1, 'REACHES THE BROWSER via an `hx-get` to `{{ api_base }}`.'),
    'couchpotato/__init__.py': (
        1,
        'REACHES THE BROWSER through `/getkey/`, which RETURNS the api_key as '
        'JSON for a username and password. Pre-existing, kept because the '
        'userscript uses it, and rate limited by this PR (AC-SEC-42, D14) '
        'precisely because it is a credential-guessing target with a better '
        'prize than the login form.',
    ),

    # --- Server side only. Listed so "not on this list" means "not looked
    # --- at", rather than "someone decided it was fine".
    'couchpotato/runner.py': (
        1, 'SERVER SIDE. Passes the key to `create_app` so `/api/<key>/` can '
           'authenticate. Never rendered.'),
    'couchpotato/core/logger.py': (
        1, 'SERVER SIDE, and the opposite of an exposure: `PrivacyFilter` '
           'caches the key in order to REDACT it out of log records.'),
    'couchpotato/core/_base/_core.py': (
        1, 'SERVER SIDE. `createApiUrl` builds the API base for notification '
           'plugins that call back into this instance. Not rendered into a '
           'page.'),
}

PY_PATTERN = re.compile(r"Env\.setting\(\s*['\"]api_key['\"]\s*\)")
TEMPLATE_PATTERN = re.compile(r'\{\{\s*api_(?:key|base)\s*\}\}')


def shipped_files():
    """Everything under `couchpotato/` that ships, excluding caches.

    `libs/` is vendored third-party code and lives outside this package.
    """
    for path in sorted(PACKAGE.rglob('*')):
        if not path.is_file() or path.suffix not in ('.py', '.html'):
            continue
        if '__pycache__' in path.parts:
            continue
        yield path


def measured_exposures():
    """path (repo-relative) -> number of matches."""
    found = {}
    for path in shipped_files():
        text = path.read_text(encoding='utf-8', errors='replace')
        pattern = PY_PATTERN if path.suffix == '.py' else TEMPLATE_PATTERN

        count = 0
        for line in text.splitlines():
            stripped = line.strip()
            # Comments do not put the key anywhere. Counting them would make
            # this test fail whenever somebody EXPLAINS the rule, which is how
            # a guard gets deleted.
            if path.suffix == '.py' and stripped.startswith('#'):
                continue
            count += len(pattern.findall(line))

        if count:
            found[str(path.relative_to(REPO_ROOT))] = count
    return found


class TestTheInventoryCanSeeAnything:
    """Guard the guard.

    Every assertion below is of the form "nothing unlisted", which an empty
    measurement satisfies perfectly. Both walks in this repo's other inventory
    file reported zero at some point during development, for two different
    harness reasons.
    """

    def test_it_walks_real_files(self):
        files = list(shipped_files())
        assert len(files) > 50, len(files)
        assert any(path.suffix == '.html' for path in files)
        assert any(path.suffix == '.py' for path in files)

    def test_it_finds_the_one_everybody_knows_about(self):
        found = measured_exposures()
        assert found.get('couchpotato/ui/templates/base.html'), found

    @pytest.mark.parametrize('sample,pattern,expected', [
        ("api_key = Env.setting('api_key')", PY_PATTERN, 1),
        ('Env.setting("api_key")', PY_PATTERN, 1),
        ("Env.setting('api_key', value=x)", PY_PATTERN, 0),
        ("apiBase: '{{ api_base }}'", TEMPLATE_PATTERN, 1),
        ('{{api_key}}', TEMPLATE_PATTERN, 1),
        ('{{ movie.api_key }}', TEMPLATE_PATTERN, 0),
    ])
    def test_the_patterns_match_what_they_claim_to(self, sample, pattern, expected):
        assert len(pattern.findall(sample)) == expected


class TestEveryExposureIsListedWithAReason:
    """AC-SEC-47."""

    def test_no_unlisted_file_touches_the_api_key(self):
        found = measured_exposures()
        unlisted = sorted(set(found) - set(API_KEY_EXPOSURES))

        assert not unlisted, (
            'these files read or render the api_key and are not in '
            'API_KEY_EXPOSURES:\n  %s\n\nEvery rendered page already hands the '
            'browser the key (D7); the point of this list is that the next one '
            'is a decision somebody wrote down. Add the path WITH the reason, '
            'or do not put the key there.' % '\n  '.join(unlisted)
        )

    def test_no_listed_file_has_grown_a_new_use(self):
        found = measured_exposures()
        grown = sorted(
            '%s: %d listed, %d found' % (path, count, found[path])
            for path, (count, _) in API_KEY_EXPOSURES.items()
            if path in found and found[path] != count
        )

        assert not grown, (
            'the api_key is used more (or fewer) times than recorded:\n  %s\n\n'
            'If a new use is deliberate, update the count and say why in the '
            'reason. A path-only allowlist would let a file that already '
            'renders the key once render it ten times unreviewed.'
            % '\n  '.join(grown)
        )

    def test_the_allowlist_has_no_entries_for_files_that_no_longer_use_it(self):
        """A stale entry pre-approves whatever lands in that file next."""
        found = measured_exposures()
        stale = sorted(set(API_KEY_EXPOSURES) - set(found))

        assert not stale, (
            'API_KEY_EXPOSURES names files that no longer touch the api_key: '
            '%s. Remove them.' % stale
        )

    def test_every_entry_carries_a_reason(self):
        empty = sorted(path for path, (_, reason) in API_KEY_EXPOSURES.items()
                       if not reason.strip())
        assert not empty, empty

    def test_every_entry_says_whether_it_reaches_the_browser(self):
        """The distinction IS the criterion. An entry that does not say which
        side of the line it is on has not been reviewed, only listed."""
        vague = sorted(
            path for path, (_, reason) in API_KEY_EXPOSURES.items()
            if 'REACHES THE BROWSER' not in reason and 'SERVER SIDE' not in reason
        )
        assert not vague, vague


class TestTheResidueIsStillWhatTheSpecSaysItIs:
    """D7 names two places by file and line. Neither may vanish silently:
    if one is fixed, this PR's stated residue changed and the sentence in the
    PR body is no longer true."""

    def test_the_template_context_still_carries_it(self):
        source = (PACKAGE / 'ui' / '__init__.py').read_text(encoding='utf-8')

        assert "api_key = Env.setting('api_key')" in source
        assert "'api_base':" in source

    def test_the_app_shell_still_renders_it(self):
        source = (PACKAGE / 'ui' / 'templates' / 'base.html').read_text(encoding='utf-8')

        assert 'apiBase' in source
        assert '{{ api_base }}' in source

    def test_getkey_still_returns_it(self):
        source = (PACKAGE / '__init__.py').read_text(encoding='utf-8')

        assert "api_key_val = Env.setting('api_key')" in source
