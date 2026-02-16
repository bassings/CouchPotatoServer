"""Tests for release quality fix migration."""
import pytest
from unittest.mock import MagicMock, patch


class TestFixReleaseQuality:
    """Test fix_release_quality migration."""

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
        mock_db.all.return_value = [mock_release]
        
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
        mock_db.all.return_value = [mock_release]
        
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
        mock_db.all.return_value = [mock_release]
        
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
        mock_db.all.return_value = [mock_release]
        
        with patch('couchpotato.core.migration.fix_release_quality.fireEvent') as mock_fire:
            mock_fire.return_value = {'identifier': '2160p', 'is_3d': False}
            
            fixed, checked = fix_release_quality(mock_db)
            
            assert fixed == 1
            mock_fire.assert_called_once()
