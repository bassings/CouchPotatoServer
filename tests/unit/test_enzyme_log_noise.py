"""Keep Enzyme's ignored-element chatter out of operational error logs."""

from contextlib import contextmanager
import logging
from pathlib import Path

from couchpotato.core.logger import setup_logging
from couchpotato.core.plugins.scanner.media_parser import MediaParserMixin


SYNTHETIC_MKV = Path(__file__).resolve().parents[1] / 'fixtures/media/unknown-ebml-element.mkv'


class _Parser(MediaParserMixin):
    def findYear(self, _text):
        return ''


@contextmanager
def _production_log(path):
    root = logging.getLogger()
    old_handlers = tuple(root.handlers)
    old_root_level = root.level
    names = ('enzyme', 'guessit', 'subliminal', 'apscheduler', 'uvicorn', 'requests')
    old_library_levels = {name: logging.getLogger(name).level for name in names}
    enzyme_parser_logger = logging.getLogger('enzyme.parsers.ebml.core')
    old_filters = tuple(enzyme_parser_logger.filters)

    setup_logging(log_path=str(path), console=False)
    try:
        yield
    finally:
        for handler in tuple(root.handlers):
            if handler not in old_handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(old_root_level)
        for name, level in old_library_levels.items():
            logging.getLogger(name).setLevel(level)
        for filt in tuple(enzyme_parser_logger.filters):
            if filt not in old_filters:
                enzyme_parser_logger.removeFilter(filt)


def test_ignored_unknown_element_is_quiet_but_real_errors_remain(tmp_path):
    log_path = tmp_path / 'app.log'
    with _production_log(log_path):
        metadata = _Parser().getMeta(str(SYNTHETIC_MKV))
        logging.getLogger('enzyme.parsers.ebml.core').error('Actual parser failure marker')

    output = log_path.read_text()
    assert metadata['video'] == 'H264'
    assert metadata['resolution_width'] == 16
    assert 'Element with id 0x55b0 is not in the specs' not in output
    assert 'Actual parser failure marker' in output


def test_unreadable_mkv_warns_without_private_path(tmp_path):
    media_file = tmp_path / 'Private Film 2026.mkv'
    media_file.write_bytes(b'not an MKV')
    log_path = tmp_path / 'app.log'

    with _production_log(log_path):
        assert _Parser().getMeta(str(media_file)) == {}

    output = log_path.read_text()
    assert 'Unable to parse media metadata' in output
    assert str(media_file) not in output
    assert 'Private Film' not in output


def test_ordinary_mp4_does_not_warn_from_mkv_parser(tmp_path):
    media_file = tmp_path / 'Private Film 2026.mp4'
    media_file.write_bytes(b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom')
    log_path = tmp_path / 'app.log'

    with _production_log(log_path):
        assert _Parser().getMeta(str(media_file)) == {}

    assert 'Unable to parse media metadata' not in log_path.read_text()
