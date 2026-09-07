"""Named constants for the event names SONAR-S1192 flagged as duplicated
string literals across `addEvent()` / `fireEvent()` / `fireEventAsync()`
call sites.

Event wiring in this codebase fails silently in both directions: a mistyped
name in `addEvent()` registers a listener nothing ever calls, and a mistyped
name in `fireEvent()`/`fireEventAsync()` calls nothing. Neither raises. That
has already cost this project twice -- `renamer.before`/`renamer.after` are
never fired (subtitles, trailers, notifications and metadata are silently
dead), and `app.test` has four registered listeners and zero fire sites
anywhere in the repository. A bare string literal at the call site cannot be
checked by anything short of grepping the tree by hand; importing a name that
does not exist raises `ImportError` at load time instead.

See specs/SPEC-SONAR-S1192-event-name-constants.md.
"""

APP_LOAD = 'app.load'
APP_RESTART = 'app.restart'
APP_SHUTDOWN = 'app.shutdown'
LIBRARY_QUERY = 'library.query'
LIBRARY_RELATED = 'library.related'
LIBRARY_TREE = 'library.tree'
MANAGE_UPDATE = 'manage.update'
MEDIA_GET = 'media.get'
MEDIA_RESTATUS = 'media.restatus'
MEDIA_TYPES = 'media.types'
MEDIA_WITH_STATUS = 'media.with_status'
MOVIE_UPDATE = 'movie.update'
NOTIFY_FRONTEND = 'notify.frontend'
PROFILE_DEFAULT = 'profile.default'
RELEASE_ADD = 'release.add'
RELEASE_FOR_MEDIA = 'release.for_media'
RELEASE_UPDATE_STATUS = 'release.update_status'
RELEASE_WITH_STATUS = 'release.with_status'
RENAMER_SCAN = 'renamer.scan'
SCANNER_NAME_YEAR = 'scanner.name_year'
SEARCHER_PROTOCOLS = 'searcher.protocols'
