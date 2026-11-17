"""The real settings read (`Settings.view`) for a named starting configuration.

    python -m tests.helpers.settings_view <fixture-name> [<section> ...]

Prints one JSON object shaped like the `settings` API answer, with `options`,
`values` and `combine_state` cut down to the sections named (default `newznab`).
The vitest suites feed it to the page's own row logic, so the logic is driven by
what the server really says about each stored shape (the Definitions' worked
cases, hidden rows, a legacy bytes literal) and not by a hand-written payload
that could be gentler than production.

Run from the repository root and as a MODULE, for the reason `config_readback`
gives. It does not import pytest, so it runs where only `requirements.txt` is
installed. The configuration is written to a temporary directory and never to a
real one.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for entry in (REPO_ROOT, REPO_ROOT / 'libs', REPO_ROOT / 'scripts'):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from tests.helpers.combine_groups import group_settings  # noqa: E402
from tests.helpers.config_readback import _AttributePatch  # noqa: E402


def settings_view(fixture, sections=('newznab',)):
    import seed_e2e_data

    stored = seed_e2e_data.config_fixture(fixture)
    with tempfile.TemporaryDirectory() as directory, _AttributePatch() as patch:
        with group_settings(Path(directory), patch, stored=stored) as settings:
            view = settings.view()
    return {key: {name: view[key][name] for name in sections if name in view[key]}
            for key in ('options', 'values', 'combine_state')}


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    sections = tuple(argv[2:]) or ('newznab',)
    print(json.dumps(settings_view(argv[1], sections)))


if __name__ == '__main__':
    main(sys.argv)
