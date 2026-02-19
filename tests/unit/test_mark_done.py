"""Unit tests for media done endpoint behavior."""
from unittest.mock import MagicMock, patch

from couchpotato.core.media._base.media.main import MediaPlugin


def test_mark_done_sets_status_to_done():
    """markDone updates media status and persists it."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    movie = {"_id": "movie-1", "status": "active"}
    db = MagicMock()
    db.get.return_value = movie

    with patch("couchpotato.core.media._base.media.main.get_db", return_value=db):
        result = plugin.markDone(id="movie-1")

    assert result["success"] is True
    assert movie["status"] == "done"
    db.get.assert_called_once_with("id", "movie-1")
    db.update.assert_called_once_with(movie)


def test_mark_done_returns_error_when_media_missing():
    """markDone returns error payload when media can't be found."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    db = MagicMock()
    db.get.return_value = None

    with patch("couchpotato.core.media._base.media.main.get_db", return_value=db):
        result = plugin.markDone(id="missing-id")

    assert result["success"] is False
    assert result["error"] == "Media not found"
    db.update.assert_not_called()
