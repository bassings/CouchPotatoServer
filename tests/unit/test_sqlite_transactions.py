"""SQLite transaction behaviour tests."""

import pytest

from couchpotato.core.db.sqlite_adapter import SQLiteAdapter


class RollbackSignal(Exception):
    """A deliberate failure that must not be confused with a database error."""


@pytest.fixture
def db(tmp_path):
    adapter = SQLiteAdapter()
    adapter.create(str(tmp_path / "testdb"))
    yield adapter
    adapter.close()


def test_transaction_commits_multiple_writes(db):
    with db.transaction():
        first = db.insert({"_t": "media", "title": "First"})
        second = db.insert({"_t": "media", "title": "Second"})

    assert db.get("id", first["_id"])["title"] == "First"
    assert db.get("id", second["_id"])["title"] == "Second"


def test_transaction_rolls_back_all_writes_on_failure(db):
    created = None

    def fail_transaction():
        nonlocal created
        with db.transaction():
            created = db.insert({"_t": "media", "title": "Rollback Me"})
            assert db.get("id", created["_id"])["title"] == "Rollback Me"
            raise RollbackSignal("boom")

    with pytest.raises(RollbackSignal):
        fail_transaction()

    with pytest.raises(KeyError):
        db.get("id", created["_id"])


def test_nested_transaction_rolls_back_inner_savepoint_only(db):
    inner = None

    def fail_inner_transaction():
        nonlocal inner
        with db.transaction():
            inner = db.insert({"_t": "media", "title": "Inner"})
            raise RollbackSignal("boom")

    with db.transaction():
        outer = db.insert({"_t": "media", "title": "Outer"})
        with pytest.raises(RollbackSignal):
            fail_inner_transaction()

    assert db.get("id", outer["_id"])["title"] == "Outer"
    with pytest.raises(KeyError):
        db.get("id", inner["_id"])
