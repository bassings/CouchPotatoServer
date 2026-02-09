"""Tests for database fixture data structure and CodernityDB interactions.

These tests validate our fixture data matches the expected CouchPotatoServer
data model, and test database operations using mocks (since CodernityDB
requires careful setup). This ensures the test infrastructure works before
we test real DB operations in integration tests.
"""
import json
import os
import pytest
from tests.helpers.database import (
    load_fixture_data, get_media_by_status, get_media_by_imdb,
    get_releases_for_quality, count_records_by_type
)


pytestmark = pytest.mark.unit


class TestFixtureDataStructure:
    """Verify the sample_data.json fixture has the expected schema."""

    def test_fixture_loads_successfully(self, sample_data):
        assert sample_data is not None
        assert isinstance(sample_data, dict)

    def test_contains_all_record_types(self, sample_data):
        expected = {'media', 'release', 'quality', 'profile', 'notification', 'property', '_meta'}
        assert expected == set(sample_data.keys())

    def test_media_records_have_required_fields(self, sample_data):
        required = {'_t', 'status', 'title', 'type', 'identifiers', 'info'}
        for media in sample_data['media']:
            missing = required - set(media.keys())
            assert not missing, f"Media '{media.get('title')}' missing: {missing}"

    def test_media_identifiers_contain_imdb(self, sample_data):
        for media in sample_data['media']:
            imdb = media.get('identifiers', {}).get('imdb')
            assert imdb is not None, f"Media '{media['title']}' has no IMDB id"
            assert imdb.startswith('tt'), f"IMDB id '{imdb}' doesn't start with 'tt'"

    def test_release_records_have_required_fields(self, sample_data):
        required = {'_t', 'status', 'media_id', 'identifier', 'quality'}
        for release in sample_data['release']:
            missing = required - set(release.keys())
            assert not missing, f"Release '{release.get('identifier')}' missing: {missing}"

    def test_quality_records_structure(self, sample_data):
        for q in sample_data['quality']:
            assert q['_t'] == 'quality'
            assert 'identifier' in q
            assert 'size_min' in q
            assert 'size_max' in q
            assert q['size_min'] < q['size_max'], \
                f"Quality '{q['identifier']}': min ({q['size_min']}) >= max ({q['size_max']})"

    def test_profile_records_have_qualities_list(self, sample_data):
        for p in sample_data['profile']:
            assert p['_t'] == 'profile'
            assert isinstance(p['qualities'], list)
            assert len(p['qualities']) > 0, f"Profile '{p['label']}' has no qualities"
            assert len(p['qualities']) == len(p['wait_for'])
            assert len(p['qualities']) == len(p['finish'])

    def test_meta_record_counts(self, sample_data):
        """The _meta block should report realistic record counts from the real DB."""
        meta = sample_data['_meta']
        assert meta['total_records'] == 2892
        assert meta['record_counts']['media'] == 849


class TestDatabaseHelpers:
    """Test the helper functions for querying fixture data."""

    def test_get_media_by_status_done(self, sample_data):
        done = get_media_by_status(sample_data, 'done')
        assert len(done) == 2
        titles = {m['title'] for m in done}
        assert 'The Lost City' in titles

    def test_get_media_by_status_active(self, sample_data):
        active = get_media_by_status(sample_data, 'active')
        assert len(active) == 1
        assert active[0]['title'] == 'Cats'

    def test_get_media_by_imdb_found(self, sample_data):
        media = get_media_by_imdb(sample_data, 'tt13320622')
        assert media is not None
        assert media['title'] == 'The Lost City'

    def test_get_media_by_imdb_not_found(self, sample_data):
        assert get_media_by_imdb(sample_data, 'tt0000000') is None

    def test_get_releases_for_quality(self, sample_data):
        releases_720 = get_releases_for_quality(sample_data, '720p')
        assert len(releases_720) == 2

    def test_count_records_by_type(self, sample_data):
        counts = count_records_by_type(sample_data)
        assert counts['media'] == 3
        assert counts['release'] == 3
        assert counts['quality'] == 4
        assert counts['profile'] == 3
