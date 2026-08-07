"""The login page's contrast, focus and target-size floor. AC-A11Y-2/3/6/13/14/15.

Computed from the colours the page ACTUALLY renders -- the class attributes are
read out of a real response and resolved against the token definitions in the
same document -- rather than asserted from a comment. Every ratio in the
implementation's comments is reproduced here; if a token moves, the arithmetic
moves with it and this file is what notices.

axe-core does not cover any of this. It has no automated focus-indicator
contrast check at all, and it cannot see a colour that is only reachable in the
theme the scan did not run in. The E2E a11y run is a second opinion, not the
proof.

Three of the four defects pinned here were live on this page before this
change, measured on the tranche B tip:

    submit button label  text-cp-bg on bg-cp-accent   1.85:1 in light
    focus indicator      #35c5f4 with no light override 1.85:1 in light
    "Remember me" target 16px box in a ~20px label     under the 24px floor

and the fourth is the trap the obvious fix walks into: `text-cp-danger` for the
new message reads 4.93:1 on the dark card and 3.67:1 on the light one.
"""
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_HTML = REPO_ROOT / 'couchpotato' / 'ui' / 'templates' / 'base.html'
LOGIN_HTML = REPO_ROOT / 'couchpotato' / 'templates' / 'login.html'

API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'

#: WCAG 2.2 AA 1.4.3 (text) and 1.4.11 (UI components).
MIN_TEXT_RATIO = 4.5
MIN_NON_TEXT_RATIO = 3.0
#: WCAG 2.2 AA 2.5.8 Target Size (Minimum). NOT the 44px house figure: that was
#: explicitly vetoed for this form at planning.
MIN_TARGET_PX = 24


# --- colour arithmetic -------------------------------------------------------

def _relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip('#')
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def composite(foreground: str, background: str, alpha: float) -> str:
    """`foreground` at `alpha` over an opaque `background`, as Tailwind's
    `bg-<token>/<n>` renders it."""
    f = [int(foreground.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(background.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    return '#%02x%02x%02x' % tuple(
        round(alpha * f[i] + (1 - alpha) * b[i]) for i in range(3))


def test_the_arithmetic_is_right():
    """Guard the guard. A broken ratio function passes everything."""
    assert contrast_ratio('#000000', '#ffffff') == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio('#ffffff', '#ffffff') == pytest.approx(1.0, abs=0.01)
    assert composite('#ffffff', '#000000', 0.5) == '#808080'
    assert composite('#f04848', '#ffffff', 0.20) == '#fcdada'


# --- reading the page's own tokens ------------------------------------------

def _theme_variables(html: str, theme: str) -> dict:
    """`--cp-*` for one theme, read from the document that uses them."""
    pattern = r':root\.light\s*\{(.*?)\}' if theme == 'light' else r':root\s*\{(.*?)\}'
    block = re.search(pattern, html, re.S)
    assert block, 'no %s theme variable block' % theme
    return {'cp-%s' % name: value
            for name, value in re.findall(r'--cp-([a-z]+):\s*(#[0-9a-fA-F]{6})', block.group(1))}


def _palette(html: str, theme: str) -> dict:
    """Every colour a `bg-`/`text-` class on this page can resolve to."""
    literals = dict(re.findall(r"\b([a-zA-Z]+):\s*'(#[0-9a-fA-F]{6})'", html))
    palette = {'cp-%s' % name: value for name, value in literals.items()}
    palette.update(_theme_variables(html, theme))
    palette['black'] = '#000000'
    palette['white'] = '#ffffff'
    return palette


def _classes(tag: str) -> list:
    match = re.search(r'\bclass="([^"]*)"', tag)
    return match.group(1).split() if match else []


def _resolve(classes, prefix, palette):
    """The colour a `<prefix>-<token>` class resolves to, plus its alpha."""
    for cls in classes:
        match = re.match(r'^%s-([a-zA-Z-]+?)(?:/(\d+))?$' % prefix, cls)
        if match and match.group(1) in palette:
            return palette[match.group(1)], (int(match.group(2)) / 100 if match.group(2) else 1.0)
    return None, None


# --- the page under test -----------------------------------------------------

@pytest.fixture
def client(tmp_path):
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('dev', False)
    Env.set('data_dir', str(tmp_path))

    data = {
        'username': '', 'password': hash_password(md5(PASSWORD)), 'api_key': API_KEY,
        'auth_required': 1, 'rate_limit_max': 0, 'cors_origins': '',
        'ssl_cert': '', 'ssl_key': '',
    }
    original = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            data[key] = kwargs['value']
            return
        return data.get(key, kwargs.get('default', ''))

    Env.setting = staticmethod(mock_setting)

    from couchpotato import create_app
    yield TestClient(create_app(API_KEY, '/'), follow_redirects=False)

    Env.setting = original
    api.clear()
    api.update(old_api)
    api_locks.clear()
    api_locks.update(old_locks)
    api_nonblock.clear()
    api_nonblock.update(old_nonblock)
    api_docs.clear()
    api_docs.update(old_docs)
    api_docs_missing.clear()
    api_docs_missing.extend(old_missing)


@pytest.fixture
def notice_page(client):
    """The login page carrying a `status` message."""
    return client.get('/login/?reason=signed_out').text


@pytest.fixture
def error_page(client):
    """The login page carrying an `alert` message, after a real rejection."""
    return client.post('/login/', data={'username': '', 'password': 'wrong'}).text


THEMES = ['dark', 'light']


class TestTheSubmitButtonLabel:
    """AC-A11Y-2."""

    @pytest.mark.parametrize('theme', THEMES)
    def test_it_meets_text_contrast(self, notice_page, theme):
        palette = _palette(notice_page, theme)
        button = re.search(r'<button[^>]*type="submit"[^>]*>', notice_page)
        assert button, 'no submit button on the login page'
        classes = _classes(button.group(0))

        fg, _ = _resolve(classes, 'text', palette)
        bg, _ = _resolve(classes, 'bg', palette)
        assert fg and bg, (classes, sorted(palette))
        ratio = contrast_ratio(fg, bg)

        assert ratio >= MIN_TEXT_RATIO, (
            'the %s-theme submit label is %s on %s = %.2f:1, under WCAG 1.4.3 '
            "AA's %.1f:1. `text-cp-bg` resolves to the PAGE background, which "
            'is nearly white in the light theme.' % (theme, fg, bg, ratio, MIN_TEXT_RATIO))


class TestTheFocusIndicator:
    """AC-A11Y-3."""

    def _outline(self, html, theme):
        if theme == 'light':
            match = re.search(
                r':root\.light\s+:focus-visible\s*\{[^}]*outline-color:\s*(#[0-9a-fA-F]{6})', html)
            assert match, (
                'login.html has no `:root.light :focus-visible` override. The '
                'dark accent measures 1.85:1 on the light background, so '
                'without it the light theme has no visible focus indicator.')
        else:
            match = re.search(
                r'(?<!light )\:focus-visible\s*\{[^}]*outline:\s*\d+px\s+solid\s+(#[0-9a-fA-F]{6})',
                html)
            assert match, 'login.html has no `:focus-visible` outline rule'
        return match.group(1)

    @pytest.mark.parametrize('theme', THEMES)
    @pytest.mark.parametrize('surface', ['cp-bg', 'cp-card', 'cp-surface'])
    def test_it_meets_non_text_contrast_on_every_surface_it_lands_on(
            self, notice_page, theme, surface):
        """Not just the page background: the controls sit on the card."""
        palette = _palette(notice_page, theme)
        outline = self._outline(notice_page, theme)
        ratio = contrast_ratio(outline, palette[surface])

        assert ratio >= MIN_NON_TEXT_RATIO, (
            'the %s-theme focus ring is %s on %s %s = %.2f:1, under WCAG '
            "1.4.11 AA's %.1f:1"
            % (theme, outline, surface, palette[surface], ratio, MIN_NON_TEXT_RATIO))

    def test_no_control_cancels_the_outline(self, notice_page):
        """`focus:outline-none` compiles to `outline: 2px solid transparent`.

        It wins on specificity over the `:focus-visible` rule above, so a
        control carrying it has no outline at all -- only the
        `focus:ring-cp-accent` ring, which measures 2.01:1 on the light
        surface. Every focusable control on this page carried it.
        """
        controls = re.findall(r'<(?:input|button|a)\b[^>]*>', notice_page)
        assert controls, 'no controls found to check'
        offenders = [c for c in controls if 'focus:outline-none' in c]

        assert offenders == [], (
            'these controls cancel their own focus outline: %s' % offenders)

    def test_the_ring_the_design_system_uses_is_still_there(self, notice_page):
        """The outline is the indicator that MEETS contrast; the ring is the
        design-system affordance and must not be dropped by the fix."""
        assert 'focus:ring-cp-accent' in notice_page


class TestTheStatusMessage:
    """AC-A11Y-6, in both tones and both themes."""

    @pytest.mark.parametrize('theme', THEMES)
    @pytest.mark.parametrize('page', ['notice_page', 'error_page'])
    def test_the_message_text_meets_contrast_on_its_own_panel(self, request, theme, page):
        html = request.getfixturevalue(page)
        palette = _palette(html, theme)
        region = re.search(r'<div[^>]*data-testid="login-message"[^>]*>', html)
        assert region, 'the %s rendered no message region' % page
        classes = _classes(region.group(0))

        fg, _ = _resolve(classes, 'text', palette)
        tint, alpha = _resolve(classes, 'bg', palette)
        assert fg and tint, (classes, sorted(palette))
        assert alpha is not None and alpha < 1.0, (
            'the panel is an opaque fill rather than a tint of an existing '
            'token: %s' % classes)

        # The panel sits on the card, so the effective background is the tint
        # composited over it -- not the tint's own colour.
        panel = composite(tint, palette['cp-card'], alpha)
        ratio = contrast_ratio(fg, panel)

        assert ratio >= MIN_TEXT_RATIO, (
            'the %s message text is %s on %s (%s at %.0f%% over the %s card '
            '%s) = %.2f:1, under %.1f:1'
            % (theme, fg, panel, tint, alpha * 100, theme, palette['cp-card'],
               ratio, MIN_TEXT_RATIO))

    @pytest.mark.parametrize('theme', THEMES)
    def test_the_obvious_choice_is_recorded_as_non_compliant(self, notice_page, theme):
        """`text-cp-danger` on the card. Pinned so the next person does not
        re-discover it by shipping it: it passes in dark and fails in light,
        which is exactly the shape a single-theme review misses."""
        palette = _palette(notice_page, theme)
        ratio = contrast_ratio(palette['cp-danger'], palette['cp-card'])

        expected = {'dark': 4.93, 'light': 3.67}[theme]
        assert ratio == pytest.approx(expected, abs=0.01)
        if theme == 'light':
            assert ratio < MIN_TEXT_RATIO

    @pytest.mark.parametrize('page', ['notice_page', 'error_page'])
    def test_the_message_does_not_rely_on_colour_alone(self, request, page):
        """WCAG 1.4.1: the two tones differ in wording, not just in tint."""
        html = request.getfixturevalue(page)
        region = re.search(
            r'<div[^>]*data-testid="login-message"[^>]*>(.*?)</div>', html, re.S)
        text = ' '.join(re.sub(r'<[^>]+>', ' ', region.group(1)).split())

        assert len(text) > 20, text


class TestTargetSize:
    """AC-A11Y-13."""

    def test_the_remember_me_label_clears_the_wcag_floor(self, notice_page):
        label = re.search(r'<label[^>]*for="remember_me"[^>]*>', notice_page)
        assert label, 'no label associated with the remember-me checkbox'
        classes = _classes(label.group(0))

        heights = [int(m.group(1)) for m in
                   (re.match(r'^min-h-\[(\d+)px\]$', c) for c in classes) if m]
        assert heights, (
            'the target is the LABEL (its `for=` activates the checkbox), and '
            'it has no minimum height: a 16px checkbox in a ~20px label is '
            'under the %dpx WCAG 2.2 AA 2.5.8 floor. classes=%s'
            % (MIN_TARGET_PX, classes))
        assert max(heights) >= MIN_TARGET_PX, classes


class TestNoNewColourAndNoNewMotion:
    """AC-A11Y-14's grep half and AC-A11Y-15."""

    @pytest.mark.parametrize('page', ['notice_page', 'error_page'])
    def test_the_markup_introduces_no_raw_hex(self, request, page):
        """Only the token definitions may name a colour."""
        html = request.getfixturevalue(page)
        # `re.I` as well as `re.S`: without it `<STYLE>` is not stripped, and
        # the hex inside it is then reported as a raw colour in the markup --
        # a false failure, and the shape CodeQL flags as `py/bad-tag-filter`.
        # `\s*` before the closing `>` as well as `re.I`: HTML permits
        # `</script >`, and an end-tag pattern that misses it leaves the whole
        # block in the markup -- so its hex would be reported as a raw colour.
        # A false FAILURE here rather than a hole, but `py/bad-tag-filter`
        # flags the shape either way, and it flagged this twice: once for case
        # and once for whitespace, because the first fix only addressed case.
        # `</style\b[^>]*>`, not `</style\s*>`: an HTML end tag may carry
        # whitespace AND ignored junk before the `>` (`</script\t\n bar>` is a
        # valid end tag). CodeQL flagged this three times -- once for case,
        # once for whitespace, once for the junk -- because each fix addressed
        # only the shape named in the previous report.
        markup = re.sub(r'<style\b.*?</style\b[^>]*>', '', html, flags=re.S | re.I)
        markup = re.sub(r'<script\b.*?</script\b[^>]*>', '', markup, flags=re.S | re.I)
        markup = re.sub(r'<meta[^>]*>', '', markup, flags=re.I)

        assert not re.search(r'#[0-9a-fA-F]{3,8}\b', markup), (
            'a raw hex colour appears outside the token blocks: %s'
            % re.findall(r'.{40}#[0-9a-fA-F]{3,8}.{20}', markup))

    def test_this_page_adds_no_animation(self, notice_page):
        assert 'animate-' not in notice_page
        assert '@keyframes' not in notice_page

    @pytest.mark.parametrize('template', [LOGIN_HTML, BASE_HTML])
    def test_motion_is_capped_under_prefers_reduced_motion(self, template):
        """The transitions both templates DO carry must be reduced."""
        css = template.read_text(encoding='utf-8')
        block = re.search(
            r'@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?\n  \})', css, re.S)
        assert block, '%s has no prefers-reduced-motion block' % template.name
        assert 'transition-duration: 0.01ms !important' in block.group(1), block.group(1)


class TestTheErrorMessageIsAssociatedWithTheField:
    """WCAG 3.3.1. Finding M4.

    A rejected sign-in moves focus INTO the password field, past a message
    region that sits before the form. The region carries `role="alert"`, but a
    `role=alert` that is part of the INITIAL document rather than inserted
    afterwards is announced inconsistently across screen readers -- and nothing
    else points at it. So a screen reader user can land in the password field
    with no indication of why they are back on this page.

    The text is present, which is why this passes an automated check; the
    association a user actually navigates by is not.
    """

    def _rejected(self, client):
        return client.post('/login/', data={'username': '', 'password': 'wrong'}).text

    def test_the_message_region_has_an_id_to_point_at(self, client):
        html = self._rejected(client)

        # NOT a substring check: `data-testid="login-message"` CONTAINS
        # `id="login-message"`, so the obvious assertion passes against a
        # region that has no id at all. It did, on the first run of this test.
        import re
        assert re.search(r'(?<![-\w])id="login-message"', html), (
            'the message region has no id of its own (data-testid does not '
            'count), so aria-describedby has nothing to reference')

    def test_the_password_field_points_at_the_message(self, client):
        html = self._rejected(client)
        field = html[html.index('id="password"'):]
        field = field[:field.index('>')]

        assert 'aria-describedby="login-message"' in field, (
            'the password field does not reference the error message, so a '
            'screen reader user lands in it with no stated reason: %s' % field)
        assert 'aria-invalid="true"' in field, (
            'the field is not marked invalid after a rejected attempt')

    def test_a_first_visit_marks_nothing_invalid(self, client):
        """Counterweight. A field that is always aria-invalid says nothing,
        and announces an error to someone who has not made one."""
        html = client.get('/login/').text
        field = html[html.index('id="password"'):]
        field = field[:field.index('>')]

        assert 'aria-invalid' not in field, field
        assert 'aria-describedby' not in field, field


class TestTheNoticeIsAssociatedWithWhereFocusLands:
    """P2 review finding. WCAG 3.3.1, the notice case rather than the error one.

    After an expiry, a revocation, or the D5 upgrade, the user is redirected
    here and focus goes straight to Username. The explanation sits above the
    form in a `role="status"` region that was already in the document when it
    loaded -- and static live-region content is not reliably announced on
    initial load. Nothing described the focused field either.

    So the person is dropped into a text box with no stated reason for having
    been interrupted, and never hears that their existing password still
    works. The error case was fixed earlier in this PR; this is the same
    defect on the path a user is far more likely to hit.
    """

    def _page(self, client, reason):
        return client.get('/login/?reason=%s' % reason).text

    def _attrs_of(self, html, element_id):
        field = html[html.index('id="%s"' % element_id):]
        return field[:field.index('>')]

    @pytest.mark.parametrize('reason', ['signed_out', 'session_ended'])
    def test_the_initially_focused_field_points_at_the_notice(self, client, reason):
        html = self._page(client, reason)
        username = self._attrs_of(html, 'username')

        assert 'autofocus' in username, (
            'focus no longer lands on username for %r, so this test is '
            'measuring the wrong field' % reason)
        assert 'aria-describedby="login-message"' in username, (
            'the field that receives focus does not reference the notice, so '
            'a screen-reader user lands in it with no stated reason: %s' % username)

    @pytest.mark.parametrize('reason', ['signed_out', 'session_ended'])
    def test_a_notice_does_not_mark_the_field_invalid(self, client, reason):
        """A notice is not a mistake. `aria-invalid` here would announce an
        error to somebody who has not made one."""
        username = self._attrs_of(self._page(client, reason), 'username')

        assert 'aria-invalid' not in username, username

    def test_a_first_visit_still_references_nothing(self, client):
        """The counterweight: no message, no association to make."""
        username = self._attrs_of(client.get('/login/').text, 'username')

        assert 'aria-describedby' not in username, username
