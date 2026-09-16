"""Regression tests for process-level OSError handling in CouchPotato.py."""

import ast
import errno
import inspect
import io
import logging
import textwrap
import traceback
from unittest.mock import Mock

import pytest

import CouchPotato as entrypoint
from couchpotato.core.logger import CPLog

pytestmark = pytest.mark.unit


class RaisingLoader:
    def __init__(self, error):
        self.error = error
        self.log = Mock()

    def daemonize(self):
        pass

    def run(self):
        raise self.error


def test_path_safe_oserror_has_no_nested_conditional_expression():
    source = textwrap.dedent(inspect.getsource(entrypoint._path_safe_oserror))
    tree = ast.parse(source)

    for expression in (node for node in ast.walk(tree) if isinstance(node, ast.IfExp)):
        assert not any(
            child is not expression and isinstance(child, ast.IfExp)
            for child in ast.walk(expression)
        )


def test_non_eintr_oserror_policy_is_testable_outside_main_control_flow():
    private_path = '/media/private/Secret Movie (2026)/file.mkv'
    error = PermissionError(errno.EACCES, 'permission denied', private_path)
    loader = RaisingLoader(error)

    with pytest.raises(OSError) as raised:
        entrypoint._handle_oserror(loader, error)

    assert raised.value.errno == errno.EACCES
    assert private_path not in str(raised.value)
    loader.log.critical.assert_called_once_with(
        '%s', '[errno 13] Permission denied', exc_info=False,
    )


def test_non_eintr_oserror_is_logged_and_propagated_without_its_private_path():
    private_path = '/media/private/Secret Movie (2026)/file.mkv'
    error = PermissionError(errno.EACCES, 'permission denied', private_path)
    loader = RaisingLoader(error)
    log_output = io.StringIO()
    handler = logging.StreamHandler(log_output)
    logger = CPLog('test-entrypoint-oserror')
    logger.logger.handlers = [handler]
    logger.logger.setLevel(logging.CRITICAL)
    logger.logger.propagate = False
    loader.log = logger

    with pytest.raises(OSError) as raised:
        entrypoint.main(loader_factory=lambda: loader)

    assert raised.value.errno == errno.EACCES
    assert private_path not in str(raised.value)
    assert private_path not in log_output.getvalue()
    assert private_path not in ''.join(traceback.format_exception(raised.value))
    assert raised.value.__suppress_context__ is True
    assert 'Permission denied' in log_output.getvalue()


def test_oserror_before_loader_exists_uses_path_safe_stderr(capsys):
    private_path = '/media/private/Secret Movie (2026)/file.mkv'

    def failing_loader_factory():
        raise PermissionError(errno.EACCES, 'permission denied', private_path)

    with pytest.raises(OSError) as raised:
        entrypoint.main(loader_factory=failing_loader_factory)

    stderr = capsys.readouterr().err
    assert raised.value.errno == errno.EACCES
    assert 'Permission denied' in stderr
    assert private_path not in stderr
    assert private_path not in ''.join(traceback.format_exception(raised.value))


def test_eintr_oserror_is_treated_as_interrupted_shutdown():
    loader = RaisingLoader(OSError(errno.EINTR, 'interrupted'))

    entrypoint.main(loader_factory=lambda: loader)

    loader.log.critical.assert_not_called()


def test_keyboard_interrupt_remains_a_quiet_shutdown():
    loader = RaisingLoader(KeyboardInterrupt())

    entrypoint.main(loader_factory=lambda: loader)

    loader.log.critical.assert_not_called()


def test_system_exit_is_still_propagated():
    loader = RaisingLoader(SystemExit(3))

    with pytest.raises(SystemExit) as raised:
        entrypoint.main(loader_factory=lambda: loader)

    assert raised.value.code == 3
    loader.log.critical.assert_not_called()


def test_other_exceptions_are_still_logged_and_propagated():
    error = RuntimeError('startup failure')
    loader = RaisingLoader(error)

    with pytest.raises(RuntimeError) as raised:
        entrypoint.main(loader_factory=lambda: loader)

    assert raised.value is error
    loader.log.critical.assert_called_once()
