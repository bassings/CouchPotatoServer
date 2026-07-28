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
