"""Unit tests for media profile attachment."""
from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin


def test_get_attaches_profile_from_profile_id():
    """get() should include profile document when profile_id exists."""
    plugin = MediaPlugin.__new__(MediaPlugin)

    media_doc = {
        "_id": "movie-1",
        "type": "movie",
        "category_id": "cat-1",
        "profile_id": "profile-1",
    }
    category_doc = {"_id": "cat-1", "label": "Movies"}
    profile_doc = {"_id": "profile-1", "label": "UHD"}

    def fake_db_get(index, key, **kwargs):
        if index == "id" and key == "movie-1":
            return dict(media_doc)
        if index == "id" and key == "cat-1":
            return category_doc
        if index == "id" and key == "profile-1":
            return profile_doc
        raise AssertionError(f"Unexpected db.get call: {(index, key, kwargs)}")

    class FakeDB:
        get = staticmethod(fake_db_get)

    with (
        patch("couchpotato.core.media._base.media.main.get_db", return_value=FakeDB()),
        patch(
            "couchpotato.core.media._base.media.main.fireEvent",
            return_value=[{"_id": "rel-1"}],
        ),
    ):
        media = plugin.get("movie-1")

    assert media["category"] == category_doc
    assert media["profile"] == profile_doc
    assert media["releases"] == [{"_id": "rel-1"}]
