"""Real-file contracts for renamer ignore markers and source cleanup."""
from pathlib import Path

from couchpotato.core.plugins.renamer.cleanup import CleanupMixin


class _Cleanup(CleanupMixin):
    def createFile(self, filename, text):
        Path(filename).write_text(text)


def test_tag_detection_and_untag_keep_exact_ignore_names(tmp_path):
    movie = tmp_path / 'movie.mkv'
    movie.write_text('downloaded movie')
    existing_marker = tmp_path / 'already.ignore'
    existing_marker.write_text('another tag')
    cleanup = _Cleanup()

    cleanup.tagRelease('hold', release_download={
        'folder': str(tmp_path), 'files': [str(movie), str(existing_marker)],
    })

    marker = tmp_path / 'movie.hold.ignore'
    assert marker.is_file()
    assert 'hold' in marker.read_text()
    assert not (tmp_path / 'already.hold.ignore').exists()
    assert cleanup.hastagRelease({'folder': str(tmp_path), 'files': []}, tag='hold') is True

    cleanup.untagRelease(release_download={'folder': str(tmp_path), 'files': []}, tag='hold')

    assert not marker.exists()
    assert movie.read_text() == 'downloaded movie'
    assert existing_marker.read_text() == 'another tag'
    assert cleanup.hastagRelease({'folder': str(tmp_path), 'files': []}, tag='hold') is False


def test_delete_folder_keeps_media_and_only_cleans_marker_leftovers(tmp_path):
    folder = tmp_path / 'source'
    folder.mkdir()
    movie = folder / 'movie.mkv'
    movie.write_text('downloaded movie')
    marker = folder / 'movie.hold.ignore'
    marker.write_text('tag')
    cleanup = _Cleanup()

    assert cleanup.deleteFolder(str(folder)) is False
    assert movie.read_text() == 'downloaded movie'
    assert marker.is_file()

    movie.unlink()
    assert cleanup.deleteFolder(str(folder)) is True
    assert not folder.exists()
