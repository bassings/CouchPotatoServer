"""Regression coverage for per-media-type API callback registration."""

from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin


def test_per_type_api_callbacks_keep_the_type_they_were_registered_for():
    """Stored callbacks must not all resolve to the loop's final media type."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    received_types = {
        "list": [],
        "available_chars": [],
        "watched": [],
        "unwatched": [],
        "watch_history": [],
        "delete": [],
    }
    received_kwargs = {operation: [] for operation in received_types}

    def record(operation):
        def callback(**kwargs):
            received_types[operation].append(kwargs["type"])
            received_kwargs[operation].append(kwargs)

        return callback

    plugin.listView = record("list")
    plugin.charView = record("available_chars")
    plugin.markWatched = record("watched")
    plugin.markUnwatched = record("unwatched")
    plugin.watchHistory = record("watch_history")
    # deleteView currently ignores ``type``; recording it here verifies only
    # that the route adapter remains independently bound, not that deletion
    # behavior consumes or dispatches on the media type.
    plugin.deleteView = record("delete")

    callbacks = {}

    def retain_callback(name, callback, **_kwargs):
        callbacks[name] = callback

    media_types = ["film", "series"]
    with patch(
        "couchpotato.core.media._base.media.main.fireEvent",
        return_value=media_types,
    ), patch(
        "couchpotato.core.media._base.media.main.addApiView",
        side_effect=retain_callback,
    ):
        plugin.addSingleListView()
        plugin.addSingleCharView()
        plugin.addSingleWatchViews()
        plugin.addSingleDeleteView()

    # Invoke only after every registration loop has finished. This is the
    # point where a late-bound closure resolves every callback to "series".
    for media_type in media_types:
        for operation in received_types:
            callbacks[f"{media_type}.{operation}"]()

    # API query/body fields are forwarded as keyword arguments. Neither the
    # closure's private capture nor a public ``type`` field may override (or
    # collide with) the type encoded by the registered route.
    for operation in received_types:
        callbacks[f"film.{operation}"](media_type="series")
        callbacks[f"film.{operation}"](type="series")
        callbacks[f"film.{operation}"]("series")
        callbacks[f"film.{operation}"](marker="forwarded")

    assert received_types == {
        operation: [*media_types, "film", "film", "film", "film"]
        for operation in received_types
    }
    assert all(
        calls[-1] == {"marker": "forwarded", "type": "film"}
        for calls in received_kwargs.values()
    )
