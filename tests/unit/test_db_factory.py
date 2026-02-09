"""Tests for the database backend factory."""
import os

import pytest

from couchpotato.core.db.factory import create_adapter, get_backend
from couchpotato.core.db.codernity_adapter import CodernityDBAdapter
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


class TestGetBackend:
    def test_default(self):
        assert get_backend() == 'codernity'

    def test_explicit(self):
        assert get_backend('sqlite') == 'sqlite'
        assert get_backend('SQLITE') == 'sqlite'
        assert get_backend('codernity') == 'codernity'

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv('CP_DATABASE_BACKEND', 'sqlite')
        assert get_backend() == 'sqlite'

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv('CP_DATABASE_BACKEND', 'sqlite')
        assert get_backend('codernity') == 'codernity'


class TestCreateAdapter:
    def test_codernity(self):
        adapter = create_adapter('codernity')
        assert isinstance(adapter, CodernityDBAdapter)

    def test_sqlite(self):
        adapter = create_adapter('sqlite')
        assert isinstance(adapter, SQLiteAdapter)

    def test_default_is_codernity(self):
        adapter = create_adapter()
        assert isinstance(adapter, CodernityDBAdapter)

    def test_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown database backend"):
            create_adapter('postgres')

    def test_env_var_creates_correct_adapter(self, monkeypatch):
        monkeypatch.setenv('CP_DATABASE_BACKEND', 'sqlite')
        adapter = create_adapter()
        assert isinstance(adapter, SQLiteAdapter)

    def test_adapters_implement_interface(self):
        from couchpotato.core.db.interface import DatabaseInterface
        codernity = create_adapter('codernity')
        sqlite = create_adapter('sqlite')
        assert isinstance(codernity, DatabaseInterface)
        assert isinstance(sqlite, DatabaseInterface)
