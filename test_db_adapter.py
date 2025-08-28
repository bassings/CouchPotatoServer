from libs.CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase
from couchpotato.db.adapter import DBAdapter


def test_db_adapter_proxies_backend(tmp_path):
    db_path = tmp_path / 'database'
    backend = SuperThreadSafeDatabase(str(db_path))
    adapter = DBAdapter(backend)

    # create via adapter backend method
    adapter.create()
    assert adapter.exists() is True

    # path and opened attributes are proxied
    assert adapter.path == str(db_path)
    # close + destroy should not raise
    adapter.close()
    adapter.destroy()

