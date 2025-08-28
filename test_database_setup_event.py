from libs.CodernityDB.database_super_thread_safe import SuperThreadSafeDatabase
from couchpotato.core.database import Database as CPDatabase
from couchpotato.core.settings import Settings
from couchpotato.core.event import fireEvent
from couchpotato.environment import Env


def test_database_setup_event_registers_property_index(tmp_path):
    # Prepare a fresh CodernityDB at a temp path and inject into Env
    db_path = tmp_path / 'database'
    cdb = SuperThreadSafeDatabase(str(db_path))
    cdb.create()
    Env.set('db', cdb)

    # Instantiate CouchPotato Database and Settings to wire events
    cp_db = CPDatabase()
    _ = Settings()  # registers the 'database.setup' handler that fires setup_index

    # Fire the database.setup event which should register the 'property' index
    fireEvent('database.setup')

    # Verify the index exists in the underlying database
    assert 'property' in cdb.indexes_names

