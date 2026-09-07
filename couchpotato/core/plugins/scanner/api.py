"""Event registration for the Scanner plugin."""

from couchpotato.core.event import addEvent
from couchpotato.core.event_names import SCANNER_NAME_YEAR


def register_scanner_events(scanner):
    """Register all scanner events on the given Scanner instance."""
    addEvent('scanner.create_file_identifier', scanner.createStringIdentifier)
    addEvent('scanner.remove_cptag', scanner.removeCPTag)
    addEvent('scanner.scan', scanner.scan)
    addEvent(SCANNER_NAME_YEAR, scanner.getReleaseNameYear)
    addEvent('scanner.partnumber', scanner.getPartNumber)
