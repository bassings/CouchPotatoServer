"""Regression tests for profile-aware available status filtering."""

from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin


def test_list_release_status_available_requires_profile_quality_match():
    """Movies are only "available" when available releases match profile qualities."""
    plugin = MediaPlugin.__new__(MediaPlugin)

    media_docs = {
        "movie-1": {
            "_id": "movie-1",
            "type": "movie",
            "status": "active",
            "profile_id": "profile-uhd",
            "title": "No Match",
        },
        "movie-2": {
            "_id": "movie-2",
            "type": "movie",
            "status": "active",
            "profile_id": "profile-uhd",
            "title": "Has Match",
        },
    }
    profile_docs = {
        "profile-uhd": {
            "_id": "profile-uhd",
            "qualities": ["2160p"],
        }
    }

    class FakeDB:
        def get(self, index, key, **kwargs):
            if index == "id" and key in media_docs:
                return dict(media_docs[key])
            if index == "id" and key in profile_docs:
                return dict(profile_docs[key])
            raise AssertionError("Unexpected db.get call: %r %r" % (index, key))

        def get_many(self, index, key):
            if index == "media_by_type" and key == "movie":
                return [{"_id": "movie-1"}, {"_id": "movie-2"}]
            return []

        def all(self, index):
            if index == "media_title":
                return [{"_id": "movie-1"}, {"_id": "movie-2"}]
            if index == "media":
                return [{"_id": "movie-1"}, {"_id": "movie-2"}]
            return []

    def fake_fire_event(event, *args, **kwargs):
        if event == "media.with_status":
            return [{"_id": "movie-1"}, {"_id": "movie-2"}]
        if event == "release.with_status":
            # Existing behavior returns both media ids because both have available releases.
            return [{"media_id": "movie-1"}, {"media_id": "movie-2"}]
        if event == "release.for_media":
            media_id = args[0]
            if media_id == "movie-1":
                return [{"status": "available", "quality": "1080p"}]
            if media_id == "movie-2":
                return [{"status": "available", "quality": "2160p"}]
            return []
        if event == "media.get":
            media_id = args[0]
            return dict(media_docs[media_id])
        raise AssertionError("Unexpected fireEvent call: %r" % (event,))

    with (
        patch("couchpotato.core.media._base.media.main.get_db", return_value=FakeDB()),
        patch("couchpotato.core.media._base.media.main.fireEvent", side_effect=fake_fire_event),
    ):
        total, movies = plugin.list(types="movie", status="active", release_status="available")

    assert total == 1
    assert [movie["_id"] for movie in movies] == ["movie-2"]
