"""Tests for release quality fix migration."""
import pytest
from unittest.mock import MagicMock, patch


class TestFixReleaseQuality:
    """Test fix_release_quality migration."""

    def _mock_get_many(self, mock_release):
        """Create a side_effect for get_many that returns release for one status only."""
        def get_many_side_effect(index_name, key, with_doc=False):
            if key == 'available':  # Only return for first status
                return [mock_release]
            return []
        return get_many_side_effect

    def test_detects_2160p_in_release_name(self):
        """Should detect 2160p quality from release name."""
        from couchpotato.core.migration.fix_release_quality import fix_release_quality

        # Mock database with a release that has wrong quality
        mock_db = MagicMock()
        mock_release = {
            'doc': {
                '_t': 'release',
                '_id': 'test123',
                '_rev': '001',
                'quality': '720p',  # Wrong - should be 2160p
                'info': {
                    'name': 'Avatar.Fire.and.Ash.2025.2160p.BluRay.x265'
                }
            }
        }
        mock_db.get_many.side_effect = self._mock_get_many(mock_release)

        # Mock quality.guess to return detected quality
        with patch('couchpotato.core.migration.fix_release_quality.fireEvent') as mock_fire:
            mock_fire.return_value = {'identifier': '2160p', 'is_3d': False}

            fixed, checked = fix_release_quality(mock_db)

            assert checked == 1
            assert fixed == 1
            # Verify db.update was called with corrected quality
            mock_db.update.assert_called_once()
            updated_doc = mock_db.update.call_args[0][0]
            assert updated_doc['quality'] == '2160p'

    def test_skips_correct_quality(self):
        """Should not update releases with correct quality."""
        from couchpotato.core.migration.fix_release_quality import fix_release_quality

        mock_db = MagicMock()
        mock_release = {
            'doc': {
                '_t': 'release',
                '_id': 'test123',
                '_rev': '001',
                'quality': '1080p',  # Already correct
                'info': {
                    'name': 'Avatar.2025.1080p.BluRay'
                }
            }
        }
        mock_db.get_many.side_effect = self._mock_get_many(mock_release)

        with patch('couchpotato.core.migration.fix_release_quality.fireEvent') as mock_fire:
            mock_fire.return_value = {'identifier': '1080p', 'is_3d': False}

            fixed, checked = fix_release_quality(mock_db)

            assert checked == 1
            assert fixed == 0
            mock_db.update.assert_not_called()

    def test_skips_releases_without_name(self):
        """Should skip releases without a name in info."""
        from couchpotato.core.migration.fix_release_quality import fix_release_quality

        mock_db = MagicMock()
        mock_release = {
            'doc': {
                '_t': 'release',
                '_id': 'test123',
                'quality': '720p',
                'info': {}  # No name
            }
        }
        mock_db.get_many.side_effect = self._mock_get_many(mock_release)

        with patch('couchpotato.core.migration.fix_release_quality.fireEvent') as mock_fire:
            fixed, checked = fix_release_quality(mock_db)

            assert checked == 1
            assert fixed == 0
            mock_fire.assert_not_called()

    def test_handles_bytes_values(self):
        """Should handle bytes values in release data."""
        from couchpotato.core.migration.fix_release_quality import fix_release_quality

        mock_db = MagicMock()
        mock_release = {
            'doc': {
                '_t': 'release',
                '_id': 'test123',
                '_rev': '001',
                'quality': b'720p',  # Bytes
                'info': {
                    'name': b'Avatar.2025.2160p.BluRay'  # Bytes
                }
            }
        }
        mock_db.get_many.side_effect = self._mock_get_many(mock_release)

        with patch('couchpotato.core.migration.fix_release_quality.fireEvent') as mock_fire:
            mock_fire.return_value = {'identifier': '2160p', 'is_3d': False}

            fixed, checked = fix_release_quality(mock_db)

            assert fixed == 1
            mock_fire.assert_called_once()

    def test_continues_past_conflict_error_on_one_release(self):
        """A ConflictError raised by db.update() on one release (a genuine
        concurrent-writer race, e.g. another process/thread touched the same
        release between this migration's read and write) must only skip
        that release, not abort the whole scan -- the remaining releases in
        the batch should still be checked/fixed."""
        from couchpotato.core.migration.fix_release_quality import fix_release_quality
        from couchpotato.core.db.sqlite_adapter import ConflictError

        mock_db = MagicMock()
        release_a = {
            'doc': {
                '_t': 'release',
                '_id': 'release-a',
                '_rev': '001',
                'quality': '720p',
                'info': {'name': 'Movie.A.2025.2160p.BluRay'},
            }
        }
        release_b = {
            'doc': {
                '_t': 'release',
                '_id': 'release-b',
                '_rev': '001',
                'quality': '720p',
                'info': {'name': 'Movie.B.2025.2160p.BluRay'},
            }
        }

        def get_many_side_effect(index_name, key, with_doc=False):
            if key == 'available':
                return [release_a, release_b]
            return []
        mock_db.get_many.side_effect = get_many_side_effect

        # First release's write loses a CAS race; second release's write
        # succeeds normally.
        mock_db.update.side_effect = [
            ConflictError('release-a'),
            {'_id': 'release-b', '_rev': '002'},
        ]

        with patch('couchpotato.core.migration.fix_release_quality.fireEvent') as mock_fire:
            mock_fire.return_value = {'identifier': '2160p', 'is_3d': False}

            fixed, checked = fix_release_quality(mock_db)

            # Both releases were checked -- the conflict on release-a did
            # not abort the scan of release-b.
            assert checked == 2
            assert fixed == 1
            assert mock_db.update.call_count == 2
