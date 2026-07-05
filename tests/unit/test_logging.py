"""Tests for the modernized logging system."""
import io
import logging
import os
import tempfile

import pytest

from couchpotato.core.logger import CPLog, ColorFormatter, PrivacyFilter, INFO2, setup_logging
from couchpotato.environment import Env


class TestCPLog:
    """Test CPLog factory."""

    def test_creates_logger(self):
        log = CPLog('test.module')
        assert isinstance(log, CPLog)
        assert log.context == 'test.module'

    def test_strips_main_suffix(self):
        log = CPLog('some.module.main')
        assert log.context == 'some.module'

    def test_truncates_long_context(self):
        log = CPLog('a' * 50)
        assert len(log.context) == 25

    def test_debug_logs(self, caplog):
        log = CPLog('test')
        with caplog.at_level(logging.DEBUG):
            log.debug('hello %s', 'world')
        assert 'hello world' in caplog.text
        assert 'test' in caplog.text

    def test_info_logs(self, caplog):
        log = CPLog('test')
        with caplog.at_level(logging.INFO):
            log.info('msg %s %s', 'a', 'b')
        assert 'msg a b' in caplog.text

    def test_info2_logs(self, caplog):
        log = CPLog('test')
        with caplog.at_level(INFO2):
            log.info2('custom level')
        assert 'custom level' in caplog.text

    def test_warning_logs(self, caplog):
        log = CPLog('test')
        with caplog.at_level(logging.WARNING):
            log.warning('warn %s', 'x')
        assert 'warn x' in caplog.text

    def test_error_logs(self, caplog):
        log = CPLog('test')
        with caplog.at_level(logging.ERROR):
            log.error('err %s', 42)
        assert 'err 42' in caplog.text

    def test_critical_logs_with_exc_info(self, caplog):
        log = CPLog('test')
        with caplog.at_level(logging.CRITICAL):
            log.critical('fatal %s', 'crash')
        assert 'fatal crash' in caplog.text

    def test_context_in_message(self, caplog):
        log = CPLog('mymodule')
        with caplog.at_level(logging.INFO):
            log.info('test message')
        assert 'mymodule' in caplog.text
        assert 'test message' in caplog.text


class TestColorFormatter:
    """Test color formatter."""

    def test_adds_color_to_debug(self):
        formatter = ColorFormatter('%(message)s')
        record = logging.LogRecord('test', logging.DEBUG, '', 0, 'hello', (), None)
        result = formatter.format(record)
        assert '\x1b[36m' in result  # cyan
        assert '\x1b[0m' in result   # reset

    def test_adds_color_to_error(self):
        formatter = ColorFormatter('%(message)s')
        record = logging.LogRecord('test', logging.ERROR, '', 0, 'error', (), None)
        result = formatter.format(record)
        assert '\x1b[31m' in result  # red

    def test_adds_color_to_warning(self):
        formatter = ColorFormatter('%(message)s')
        record = logging.LogRecord('test', logging.WARNING, '', 0, 'warn', (), None)
        result = formatter.format(record)
        assert '\x1b[33m' in result  # yellow


class TestPrivacyFilter:
    """Test privacy filter."""

    def test_redacts_api_key_param(self):
        filt = PrivacyFilter()
        filt._is_develop = False
        filt._api_key = ''
        record = logging.LogRecord('test', logging.INFO, '', 0,
                                   'url?api_key=secret123&other=ok', None, None)
        filt.filter(record)
        assert 'secret123' not in record.msg
        assert 'api_key=xxx' in record.msg

    def test_redacts_password_param(self):
        filt = PrivacyFilter()
        filt._is_develop = False
        filt._api_key = ''
        record = logging.LogRecord('test', logging.INFO, '', 0,
                                   'url?password=hunter2', None, None)
        filt.filter(record)
        assert 'hunter2' not in record.msg

    def test_redacts_api_key_value(self):
        filt = PrivacyFilter()
        filt._is_develop = False
        filt._api_key = 'mykey123'
        record = logging.LogRecord('test', logging.INFO, '', 0,
                                   'accessing mykey123 endpoint', None, None)
        filt.filter(record)
        assert 'mykey123' not in record.msg
        assert 'API_KEY' in record.msg

    def test_no_redaction_in_develop(self):
        filt = PrivacyFilter()
        filt._is_develop = True
        filt._api_key = 'mykey123'
        record = logging.LogRecord('test', logging.INFO, '', 0,
                                   'accessing mykey123 endpoint', None, None)
        filt.filter(record)
        assert 'mykey123' in record.msg

    def test_handles_format_args(self):
        filt = PrivacyFilter()
        filt._is_develop = False
        filt._api_key = ''
        record = logging.LogRecord('test', logging.INFO, '', 0,
                                   'url?apikey=%s', ('secret',), None)
        filt.filter(record)
        assert 'secret' not in record.msg


class TestSetupLogging:
    """Test setup_logging function."""

    def test_setup_console_only(self):
        # Save and restore root logger state
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        old_filters = root.filters[:]
        old_level = root.level
        try:
            root.handlers.clear()
            root.filters.clear()
            setup_logging(console=True, debug=True)
            handler_types = [type(h) for h in root.handlers]
            assert logging.StreamHandler in handler_types
        finally:
            root.handlers = old_handlers
            root.filters = old_filters
            root.level = old_level

    def test_setup_with_file(self):
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        old_filters = root.filters[:]
        old_level = root.level
        try:
            root.handlers.clear()
            root.filters.clear()
            with tempfile.NamedTemporaryFile(suffix='.log', delete=False) as f:
                log_path = f.name
            try:
                setup_logging(log_path=log_path, console=False)
                from logging.handlers import RotatingFileHandler
                handler_types = [type(h) for h in root.handlers]
                assert RotatingFileHandler in handler_types
            finally:
                # Close handlers before removing file
                for h in root.handlers:
                    h.close()
                os.unlink(log_path)
        finally:
            root.handlers = old_handlers
            root.filters = old_filters
            root.level = old_level

    def test_info2_level_registered(self):
        assert logging.getLevelName(INFO2) == 'INFO'
        assert INFO2 == 21

    def test_info2_visible_in_production_level(self):
        """REG-003 item 4: INFO2 used to be 19 (below the default INFO=20
        root level), so log.info2(...) -- release-rejection reasons,
        provider circuit-breaker trips -- was silently dropped in
        production. INFO2 must be above INFO so it's visible at the
        default (non-debug) level.

        Deliberately avoids caplog.at_level(), which sets the *logger's*
        own level directly and would mask the bug (it bypasses the
        root-level threshold this test needs to exercise). Uses a plain
        handler on the real root logger instead.
        """
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        old_filters = root.filters[:]
        old_level = root.level
        try:
            root.handlers.clear()
            root.filters.clear()
            setup_logging(console=False, debug=False)

            assert root.level == logging.INFO
            assert INFO2 > logging.INFO

            records = []

            class ListHandler(logging.Handler):
                def emit(self, record):
                    records.append(record)

            handler = ListHandler()
            handler.setLevel(0)
            root.addHandler(handler)

            log = CPLog('test.info2.visibility')
            log.info2('provider circuit breaker tripped')

            assert any('provider circuit breaker tripped' in r.getMessage() for r in records)
        finally:
            root.handlers = old_handlers
            root.filters = old_filters
            root.level = old_level

    def test_privacy_filter_applied_via_child_logger(self, monkeypatch):
        """REG-003 item 5: setup_logging attached PrivacyFilter to the ROOT
        LOGGER (`logger.addFilter(...)`). Per stdlib semantics, a Logger's
        own `.filters` only run for records that *originate* on that
        logger -- not for records propagated up from a child logger's
        `callHandlers()`. CPLog always logs through a named child logger
        (`logging.getLogger(context)`), so the filter never actually ran
        for a real log record and secrets (api_key, passkey, ...) in
        logged URLs were never redacted. The filter must be attached to
        the HANDLERS instead, since Handler.handle() re-checks its own
        filters for every record it emits regardless of origin.
        """
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        old_filters = root.filters[:]
        old_level = root.level
        try:
            root.handlers.clear()
            root.filters.clear()
            monkeypatch.setattr(Env, '_dev', False)

            setup_logging(console=True, debug=False)

            stream_handler = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
            buffer = io.StringIO()
            stream_handler.stream = buffer

            log = CPLog('test.privacy.child')
            log.info('request failed: /api/xxx?api_key=SECRETVALUE&other=1')

            output = buffer.getvalue()
            assert output, 'expected the handler to emit a record'
            assert 'SECRETVALUE' not in output
            assert 'api_key=xxx' in output
        finally:
            root.handlers = old_handlers
            root.filters = old_filters
            root.level = old_level
