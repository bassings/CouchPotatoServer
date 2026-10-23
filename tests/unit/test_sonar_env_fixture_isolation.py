"""Autouse fixtures must restore Env's process-wide class attributes."""

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ('source_module', 'fixture_name', 'present', 'missing', 'configured'),
    [
        (
            'test_releases_partial_route',
            'env',
            {'web_base': '/before/', 'dev': True},
            ('api_base', 'static_path'),
            {'web_base': '/', 'api_base': '/api/testkey123/',
             'static_path': '/static/', 'dev': False},
        ),
        (
            'test_review_actions_ui_template',
            '_env',
            {'web_base': '/before/'},
            (),
            {'web_base': '/'},
        ),
        (
            'test_notifications',
            'setup_env',
            {'appname': 'Before', 'dev': True},
            (),
            {'appname': 'CouchPotato', 'dev': False},
        ),
    ],
)
def test_autouse_fixture_restores_env_after_a_failed_test(
    pytester, monkeypatch, source_module, fixture_name, present, missing, configured,
):
    pythonpath = os.pathsep.join((
        str(REPO_ROOT), str(REPO_ROOT / 'libs'), str(REPO_ROOT / 'tests' / 'unit'),
        os.environ.get('PYTHONPATH', ''),
    ))
    monkeypatch.setenv('PYTHONPATH', pythonpath)
    pytester.makeconftest(f"""
        from couchpotato.environment import Env

        def pytest_collection_finish(session):
            for name, value in {present!r}.items():
                setattr(Env, '_' + name, value)
            for name in {missing!r}:
                if hasattr(Env, '_' + name):
                    delattr(Env, '_' + name)
    """)
    configured_checks = '\n'.join(
        f'    assert Env.get({name!r}) == {value!r}'
        for name, value in configured.items()
    )
    pytester.makepyfile(test_a=(
        'import pytest\n'
        'from couchpotato.environment import Env\n'
        f'from {source_module} import {fixture_name}\n\n'
        'def test_fixture_sets_expected_state():\n'
        f'{configured_checks}\n\n'
        "@pytest.mark.xfail(strict=True, reason='exercise teardown after assertion failure')\n"
        'def test_fixture_teardown_after_failure():\n'
        f'{configured_checks}\n'
        "    assert False, 'deliberate test-body failure'\n"
    ))
    restored_checks = '\n'.join(
        f'    assert Env.get({name!r}) == {value!r}'
        for name, value in present.items()
    )
    missing_checks = '\n'.join(
        f"    assert not hasattr(Env, {'_' + name!r})"
        for name in missing
    )
    pytester.makepyfile(test_b=(
        'from couchpotato.environment import Env\n\n'
        'def test_env_restored_after_fixture_teardown():\n'
        f'{restored_checks}\n{missing_checks}\n'
    ))

    result = pytester.runpytest_subprocess('-q', 'test_a.py', 'test_b.py')
    result.assert_outcomes(passed=2, xfailed=1)
