"""The "Downloaded / review" gate defaults ON (FEAT-004).

`specs/DOWNLOADED-REVIEW-WORKFLOW.md` decided that a completed download must
never auto-promote to `done` — the user reviews it first. The gate shipped
per-profile as `manual_confirmation`, but defaulting OFF for backwards
compatibility, which inverted the intended design: on a production install all
18 profiles had it unset, so every completion went straight to `done` and
nothing ever surfaced that the gate existed.

The subtlety worth protecting: `save()` deliberately falls back to the
PERSISTED value when the key is omitted, because the live profile editor does
not resend it. Changing the create-path default must not leak into that
fallback, or editing any existing profile would silently switch its gate on.
"""

from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.plugins.profile.main import DEFAULT_PROFILES, build_profile_doc


class TestSeededProfiles:

    @pytest.mark.parametrize('profile', DEFAULT_PROFILES, ids=lambda p: p['label'])
    def test_every_seeded_profile_has_the_gate_on(self, profile):
        """AC1: a fresh install must review downloads, not auto-complete."""
        doc = build_profile_doc(profile, order=0)

        assert doc.get('manual_confirmation') is True


class TestSaveDefaults:
    """AC2-AC5 — the create path changes, the edit path must not."""

    def _save(self, plugin, kwargs, existing=None):
        """Drive Profile.save(). `existing` None means the create path."""
        db = MagicMock()
        inserted = {}

        def fake_insert(doc):
            inserted.update(doc)
            inserted.setdefault('_id', 'new-profile')
            return inserted

        db.insert.side_effect = fake_insert
        if existing is None:
            db.get.side_effect = KeyError('not found')
        else:
            db.get.return_value = dict(existing)

        with patch('couchpotato.core.plugins.profile.main.get_db', return_value=db), \
                patch('couchpotato.core.plugins.profile.main.fireEvent'):
            plugin.save(**kwargs)

        # the doc handed to db.update is the authoritative final state
        return db.update.call_args[0][0] if db.update.called else inserted

    @pytest.fixture
    def plugin(self):
        from couchpotato.core.plugins.profile.main import ProfilePlugin

        return object.__new__(ProfilePlugin)

    def _types(self):
        return [{'quality': '1080p', 'finish': 1, '3d': 0}]

    def test_a_new_profile_gets_the_gate_on(self, plugin):
        """AC2: creating a profile without mentioning the flag opts into the
        reviewed workflow, matching the seeded profiles."""
        doc = self._save(plugin, {'label': 'New', 'types': self._types()})

        assert doc.get('manual_confirmation') is True

    def test_editing_a_profile_with_the_gate_off_leaves_it_off(self, plugin):
        """AC3: the regression this guards against. The live profile editor
        does not resend manual_confirmation, so the persisted value must win
        over the new default -- otherwise every save of an existing profile
        silently switches its gate on."""
        existing = {'_id': 'p1', 'label': 'Old', 'manual_confirmation': False,
                    'order': 3}

        doc = self._save(plugin, {'id': 'p1', 'label': 'Old', 'types': self._types()},
                         existing=existing)

        assert doc.get('manual_confirmation') is False

    def test_editing_a_profile_with_the_gate_on_leaves_it_on(self, plugin):
        """AC4: the mirror case."""
        existing = {'_id': 'p1', 'label': 'Old', 'manual_confirmation': True,
                    'order': 3}

        doc = self._save(plugin, {'id': 'p1', 'label': 'Old', 'types': self._types()},
                         existing=existing)

        assert doc.get('manual_confirmation') is True

    def test_an_explicit_zero_still_turns_it_off_on_create(self, plugin):
        """AC5: the new default must not make the flag unsettable."""
        doc = self._save(plugin, {'label': 'New', 'types': self._types(),
                                  'manual_confirmation': '0'})

        assert doc.get('manual_confirmation') is False

    def test_an_explicit_zero_still_turns_it_off_on_edit(self, plugin):
        existing = {'_id': 'p1', 'label': 'Old', 'manual_confirmation': True,
                    'order': 3}

        doc = self._save(plugin, {'id': 'p1', 'label': 'Old', 'types': self._types(),
                                  'manual_confirmation': '0'},
                         existing=existing)

        assert doc.get('manual_confirmation') is False


class TestCoreFlagSurvivesAnEdit:
    """`core` marks a built-in profile non-deletable: the settings UI disables
    its delete button and the JS guards on it.

    save() built it as `kwargs.get('core', False)` with no fallback to the
    persisted value -- unlike `order` and `manual_confirmation`. The new-UI
    profile editor sends id/label/minimum_score/wait_for/stop_after/types and
    never `core`, so **every edit of a built-in profile silently cleared the
    flag and made it deletable**. Found when a bulk profile update cleared it
    on 12 built-ins at once.
    """

    @pytest.fixture
    def plugin(self):
        from couchpotato.core.plugins.profile.main import ProfilePlugin

        return object.__new__(ProfilePlugin)

    def _save(self, plugin, kwargs, existing=None):
        db = MagicMock()
        inserted = {}

        def fake_insert(doc):
            inserted.update(doc)
            inserted.setdefault('_id', 'new-profile')
            return inserted

        db.insert.side_effect = fake_insert
        if existing is None:
            db.get.side_effect = KeyError('not found')
        else:
            db.get.return_value = dict(existing)

        with patch('couchpotato.core.plugins.profile.main.get_db', return_value=db), \
                patch('couchpotato.core.plugins.profile.main.fireEvent'):
            plugin.save(**kwargs)

        return db.update.call_args[0][0] if db.update.called else inserted

    def _types(self):
        return [{'quality': '1080p', 'finish': 1, '3d': 0}]

    def test_editing_a_builtin_without_sending_core_keeps_it(self, plugin):
        """Bug repro: this is exactly the payload the profile editor sends."""
        existing = {'_id': 'p1', 'label': '720p', 'core': True, 'order': 5}

        doc = self._save(plugin, {'id': 'p1', 'label': '720p',
                                  'minimum_score': '1', 'wait_for': '0',
                                  'stop_after': '0', 'types': self._types()},
                         existing=existing)

        assert doc.get('core') is True, (
            'editing a built-in profile cleared its core flag, making it '
            'deletable in the UI'
        )

    def test_a_non_core_profile_stays_non_core(self, plugin):
        existing = {'_id': 'p1', 'label': 'Mine', 'core': False, 'order': 5}

        doc = self._save(plugin, {'id': 'p1', 'label': 'Mine',
                                  'types': self._types()}, existing=existing)

        assert not doc.get('core')

    def test_an_explicit_core_value_still_wins(self, plugin):
        existing = {'_id': 'p1', 'label': 'Mine', 'core': False, 'order': 5}

        doc = self._save(plugin, {'id': 'p1', 'label': 'Mine', 'core': True,
                                  'types': self._types()}, existing=existing)

        assert doc.get('core') is True

    def test_a_new_profile_is_not_core(self, plugin):
        """Only the seeded built-ins are core; anything a user creates is
        theirs to delete."""
        doc = self._save(plugin, {'label': 'Mine', 'types': self._types()})

        assert not doc.get('core')


class TestQualitySeededProfiles:
    """QualityPlugin.fill() seeds a one-quality core profile per quality, and
    runs BEFORE ProfilePlugin.fill() on a fresh database. Those documents are
    built inline rather than through build_profile_doc(), so they needed the
    gate adding separately -- otherwise a fresh install still had a dozen
    profiles that auto-complete downloads."""

    def test_the_seeded_profile_document_has_the_gate_on(self):
        """Asserted on the profile-insert block specifically, so it cannot
        pass on an unrelated occurrence elsewhere in fill()."""
        import inspect
        import re

        from couchpotato.core.plugins.quality.main import QualityPlugin

        source = inspect.getsource(QualityPlugin.fill)
        block = re.search(r"'_t': 'profile'.*?\}\)", source, re.S)

        assert block, "could not find the profile insert in QualityPlugin.fill"
        assert "'manual_confirmation': True" in block.group(0)


class TestTagPersistsTheTimestampBump:
    """FEAT-005 leans on media.tag(..., update_edited=True) to keep
    release.cleanDone from sweeping the releases a search just surfaced.

    tag() had db.update() inside the tag-is-new branch, so the SECOND search
    onward bumped last_edit in memory only and the protection silently stopped
    working."""

    def _tag(self, existing_tags):
        from couchpotato.core.media._base.media.main import MediaPlugin

        plugin = object.__new__(MediaPlugin)
        doc = {'_id': 'm1', 'tags': list(existing_tags), 'last_edit': 0}
        db = MagicMock()
        db.get.return_value = doc

        with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
                patch('couchpotato.core.media._base.media.main.media_lock'):
            plugin.tag('m1', 'recent', update_edited=True)

        return doc, db

    def test_a_repeat_tag_still_persists_the_new_timestamp(self):
        """The bug: 'recent' already present, so nothing was written."""
        doc, db = self._tag(['recent'])

        assert doc['last_edit'] > 0
        assert db.update.called, (
            'last_edit was bumped in memory but never persisted, so the '
            'cleanup protection stopped working after the first search'
        )

    def test_a_first_tag_still_persists(self):
        doc, db = self._tag([])

        assert 'recent' in doc['tags']
        assert db.update.called
