"""E2E test: Existing user scenario.

Tests loading and validating existing CodernityDB data from fixtures,
simulating a user who already has a populated database. Verifies that
the fixture data is accessible, properly structured, and queryable
in the ways the app would need.
"""
import json
import os
import pytest

pytestmark = pytest.mark.e2e


class TestExistingDatabaseAccess:
    """Verify fixture data represents a real user's database correctly."""

    def test_load_all_media(self, sample_data):
        """Should load all media records from fixture."""
        media = sample_data['media']
        assert len(media) == 3
        statuses = {m['status'] for m in media}
        assert 'done' in statuses
        assert 'active' in statuses

    def test_media_info_contains_tmdb(self, sample_data):
        """Each media's info block should have TMDB metadata."""
        for media in sample_data['media']:
            info = media['info']
            assert 'tmdb_id' in info, f"'{media['title']}' missing tmdb_id"
            assert 'genres' in info
            assert isinstance(info['genres'], list)

    def test_releases_linked_to_media(self, sample_data):
        """Each release should reference a media_id."""
        for release in sample_data['release']:
            assert release['media_id'] is not None
            assert len(release['media_id']) > 0

    def test_release_statuses_valid(self, sample_data):
        """Release statuses should be one of the known values."""
        valid = {'done', 'snatched', 'available', 'wanted', 'ignored', 'deleted'}
        for release in sample_data['release']:
            assert release['status'] in valid, \
                f"Release '{release['identifier']}' has unknown status: {release['status']}"

    def test_profiles_ordered(self, sample_data):
        """Profiles should have sequential order values."""
        orders = [p['order'] for p in sample_data['profile']]
        assert sorted(orders) == orders

    def test_properties_have_identifiers(self, sample_data):
        """Property records should have identifier and value."""
        for prop in sample_data['property']:
            assert prop['_t'] == 'property'
            assert 'identifier' in prop
            assert 'value' in prop

    def test_notification_records(self, sample_data):
        """Notifications should have message and timestamp."""
        for notif in sample_data['notification']:
            assert notif['_t'] == 'notification'
            assert 'message' in notif
            assert 'time' in notif
            assert isinstance(notif['time'], int)

    def test_done_media_has_files(self, sample_data):
        """At least one 'done' media should have file references."""
        done = [m for m in sample_data['media'] if m['status'] == 'done']
        has_files = any(m.get('files') for m in done)
        assert has_files, "No 'done' media has file references"

    def test_snatched_release_has_download_info(self, sample_data):
        """Snatched releases should have download tracking info."""
        snatched = [r for r in sample_data['release'] if r['status'] == 'snatched']
        assert len(snatched) > 0
        for r in snatched:
            assert 'download_info' in r, f"Snatched release missing download_info"
            assert 'downloader' in r['download_info']
