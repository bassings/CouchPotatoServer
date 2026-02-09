"""Scanner plugin - main class composing all scanner functionality."""

from couchpotato.core.plugins.base import Plugin
from couchpotato.core.plugins.scanner.api import register_scanner_events
from couchpotato.core.plugins.scanner.file_detector import FileDetectorMixin
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin
from couchpotato.core.plugins.scanner.media_parser import MediaParserMixin

autoload = 'Scanner'


class Scanner(FileDetectorMixin, MediaParserMixin, FolderScannerMixin, Plugin):

    def __init__(self):
        register_scanner_events(self)
