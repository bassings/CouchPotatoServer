from libs.CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase


def test_codernitydb_create_exists_destroy(tmp_path):
    db_path = tmp_path / 'database'
    db = SuperThreadSafeDatabase(str(db_path))
    created_path = db.create()
    try:
        assert db.exists()
        assert str(created_path) == str(db_path)
    finally:
        db.destroy()

