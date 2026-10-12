import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event, text

data = Path(os.environ.get('HOOKSCOPE_DATA', Path(__file__).resolve().parents[1] / 'data'))
data.mkdir(parents=True, exist_ok=True)
engine = create_engine(f'sqlite:///{data / "hookscope.db"}', hide_parameters=True, connect_args={'check_same_thread': False, 'timeout': 30})


@contextmanager
def service_lock():
    """One service per database, also protecting offline restore from a live server."""
    with (data / '.service.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'1');lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('This database is already in use. Stop Hookscope before this operation.')
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

@event.listens_for(engine, 'connect')
def configure(connection, _):
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA foreign_keys=ON')

def backup_to(target: Path) -> None:
    """Consistent online backup, including committed WAL transactions."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Backup target already exists.')
    with sqlite3.connect(data / 'hookscope.db') as source, sqlite3.connect(target) as destination:
        source.backup(destination)
        if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed.')
    try:
        target.chmod(0o600)
    except OSError:
        pass


def initialize():
    statements = [
        'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS endpoints (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
            destination TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
            created REAL NOT NULL, method TEXT NOT NULL, headers TEXT NOT NULL, body BLOB NOT NULL,
            kind TEXT NOT NULL, source TEXT NOT NULL, external_id TEXT,
            UNIQUE(endpoint_id, external_id))''',
        '''CREATE TABLE IF NOT EXISTS attempts (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            created REAL NOT NULL, finished REAL, status TEXT NOT NULL, code INTEGER,
            latency INTEGER, response TEXT, error TEXT, destination TEXT NOT NULL,
            replay INTEGER NOT NULL DEFAULT 0, lease REAL, execution_count INTEGER NOT NULL DEFAULT 0)''',
        'CREATE INDEX IF NOT EXISTS events_created ON events(created)',
        'CREATE INDEX IF NOT EXISTS events_endpoint_created ON events(endpoint_id, created)',
        'CREATE INDEX IF NOT EXISTS attempts_queue ON attempts(status, created)',
        'CREATE INDEX IF NOT EXISTS attempts_event ON attempts(event_id, created)',
        'CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied REAL NOT NULL)',
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    # Back up legacy data before the first additive migration. Never discard history.
    if not query('SELECT version FROM schema_migrations WHERE version=1'):
        backup_to(data / f'pre-migration-1-{time.time_ns()}.db')
        with engine.begin() as conn:
            conn.execute(text('UPDATE settings SET value=value WHERE key=\'password\''))
            if not conn.execute(text('SELECT version FROM schema_migrations WHERE version=1')).first():
                additions = {
                    'endpoints': [('verify_mode', "TEXT NOT NULL DEFAULT 'none'"), ('incoming_secret_ref', "TEXT NOT NULL DEFAULT ''"), ('signing_secret_ref', "TEXT NOT NULL DEFAULT ''"), ('retries', 'INTEGER NOT NULL DEFAULT 0')],
                    'attempts': [('signing_secret_ref', "TEXT NOT NULL DEFAULT ''"), ('retries', 'INTEGER NOT NULL DEFAULT 0'), ('retry_count', 'INTEGER NOT NULL DEFAULT 0'), ('next_run', 'REAL NOT NULL DEFAULT 0')],
                }
                for table, columns in additions.items():
                    existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info({table})'))}
                    for name, definition in columns:
                        if name not in existing:
                            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
                conn.execute(text('CREATE TABLE IF NOT EXISTS auth_limits (key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL)'))
                conn.execute(text('CREATE TABLE IF NOT EXISTS worker_heartbeats (id TEXT PRIMARY KEY, updated REAL NOT NULL)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS attempts_due ON attempts(status,next_run,created)'))
                conn.execute(text('INSERT INTO schema_migrations(version,applied) VALUES(1,:now)'), {'now':time.time()})
    if not query('SELECT version FROM schema_migrations WHERE version=2'):
        backup_to(data / f'pre-migration-2-{time.time_ns()}.db')
        with engine.begin() as conn:
            conn.execute(text("UPDATE settings SET value=value WHERE key='password'"))
            if not conn.execute(text('SELECT version FROM schema_migrations WHERE version=2')).first():
                conn.execute(text('CREATE TABLE tenants (id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,password TEXT NOT NULL,created REAL NOT NULL)'))
                conn.execute(text("INSERT INTO tenants(id,email,password,created) SELECT 'legacy','owner@localhost',value,:now FROM settings WHERE key='password'"), {'now':time.time()})
                conn.execute(text('CREATE TABLE invitations (token TEXT PRIMARY KEY,email TEXT NOT NULL,expires REAL NOT NULL,created REAL NOT NULL)'))
                conn.execute(text('CREATE TABLE tenant_secrets (id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,name TEXT NOT NULL,value TEXT NOT NULL,UNIQUE(owner_id,name))'))
                for table in ('endpoints','sessions'):
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy'"))
                    conn.execute(text(f'CREATE INDEX {table}_owner ON {table}(owner_id)'))
                conn.execute(text('INSERT INTO schema_migrations(version,applied) VALUES(2,:now)'), {'now':time.time()})
    if not query('SELECT version FROM schema_migrations WHERE version=3'):
        backup_to(data / f'pre-migration-3-{time.time_ns()}.db')
        with engine.begin() as conn:
            conn.execute(text("UPDATE settings SET value=value WHERE key='password'"))
            if not conn.execute(text('SELECT version FROM schema_migrations WHERE version=3')).first():
                conn.execute(text("ALTER TABLE events ADD COLUMN latest_status TEXT NOT NULL DEFAULT 'received'"))
                conn.execute(text("UPDATE events SET latest_status=coalesce((SELECT status FROM attempts WHERE event_id=events.id ORDER BY created DESC,id DESC LIMIT 1),'received')"))
                conn.execute(text('CREATE INDEX events_endpoint_status ON events(endpoint_id,latest_status)'))
                conn.execute(text('CREATE INDEX attempts_completed ON attempts(event_id) WHERE finished IS NOT NULL'))
                conn.execute(text('CREATE TABLE workspace_usage(owner_id TEXT PRIMARY KEY,events INTEGER NOT NULL DEFAULT 0,body_bytes INTEGER NOT NULL DEFAULT 0,response_bytes INTEGER NOT NULL DEFAULT 0,attempt_count INTEGER NOT NULL DEFAULT 0,last_claim REAL NOT NULL DEFAULT 0)'))
                conn.execute(text('''INSERT INTO workspace_usage(owner_id,events,body_bytes,response_bytes,attempt_count)
                    SELECT t.id,(SELECT count(*) FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=t.id),
                    (SELECT coalesce(sum(length(e.body)),0) FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=t.id),
                    (SELECT coalesce(sum(length(CAST(a.response AS BLOB))),0) FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=t.id),
                    (SELECT count(*) FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=t.id) FROM tenants t'''))
                conn.execute(text('CREATE TABLE instance_usage(id INTEGER PRIMARY KEY CHECK(id=1),events INTEGER NOT NULL,body_bytes INTEGER NOT NULL,response_bytes INTEGER NOT NULL,attempt_count INTEGER NOT NULL)'))
                conn.execute(text('INSERT INTO instance_usage SELECT 1,coalesce(sum(events),0),coalesce(sum(body_bytes),0),coalesce(sum(response_bytes),0),coalesce(sum(attempt_count),0) FROM workspace_usage'))
                triggers = [
                    "CREATE TRIGGER tenant_insert AFTER INSERT ON tenants BEGIN INSERT INTO workspace_usage(owner_id) VALUES(NEW.id); END",
                    "CREATE TRIGGER tenant_delete BEFORE DELETE ON tenants BEGIN DELETE FROM endpoints WHERE owner_id=OLD.id; DELETE FROM sessions WHERE owner_id=OLD.id; DELETE FROM workspace_usage WHERE owner_id=OLD.id; END",
                    "CREATE TRIGGER endpoint_owner_immutable BEFORE UPDATE OF owner_id ON endpoints WHEN NEW.owner_id<>OLD.owner_id BEGIN SELECT RAISE(ABORT,'Workspace ownership is immutable'); END",
                    "CREATE TRIGGER endpoint_delete BEFORE DELETE ON endpoints BEGIN DELETE FROM events WHERE endpoint_id=OLD.id; END",
                    "CREATE TRIGGER event_insert AFTER INSERT ON events BEGIN UPDATE workspace_usage SET events=events+1,body_bytes=body_bytes+length(NEW.body) WHERE owner_id=(SELECT owner_id FROM endpoints WHERE id=NEW.endpoint_id); END",
                    "CREATE TRIGGER event_delete_children BEFORE DELETE ON events BEGIN DELETE FROM attempts WHERE event_id=OLD.id; END",
                    "CREATE TRIGGER event_delete AFTER DELETE ON events BEGIN UPDATE workspace_usage SET events=events-1,body_bytes=body_bytes-length(OLD.body) WHERE owner_id=(SELECT owner_id FROM endpoints WHERE id=OLD.endpoint_id); END",
                    "CREATE TRIGGER attempt_insert AFTER INSERT ON attempts BEGIN UPDATE workspace_usage SET attempt_count=attempt_count+1,response_bytes=response_bytes+coalesce(length(CAST(NEW.response AS BLOB)),0) WHERE owner_id=(SELECT p.owner_id FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=NEW.event_id); UPDATE events SET latest_status=coalesce((SELECT status FROM attempts WHERE event_id=NEW.event_id ORDER BY created DESC,id DESC LIMIT 1),'received') WHERE id=NEW.event_id; END",
                    "CREATE TRIGGER attempt_update AFTER UPDATE OF status,response ON attempts BEGIN UPDATE workspace_usage SET response_bytes=response_bytes+coalesce(length(CAST(NEW.response AS BLOB)),0)-coalesce(length(CAST(OLD.response AS BLOB)),0) WHERE owner_id=(SELECT p.owner_id FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=NEW.event_id); UPDATE events SET latest_status=coalesce((SELECT status FROM attempts WHERE event_id=NEW.event_id ORDER BY created DESC,id DESC LIMIT 1),'received') WHERE id=NEW.event_id; END",
                    "CREATE TRIGGER attempt_delete AFTER DELETE ON attempts BEGIN UPDATE workspace_usage SET attempt_count=attempt_count-1,response_bytes=response_bytes-coalesce(length(CAST(OLD.response AS BLOB)),0) WHERE owner_id=(SELECT p.owner_id FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE e.id=OLD.event_id); UPDATE events SET latest_status=coalesce((SELECT status FROM attempts WHERE event_id=OLD.event_id ORDER BY created DESC,id DESC LIMIT 1),'received') WHERE id=OLD.event_id; END",
                ]
                for trigger in triggers:
                    if trigger.startswith('CREATE TRIGGER event_insert '):
                        trigger=trigger.replace('BEGIN ','BEGIN UPDATE instance_usage SET events=events+1,body_bytes=body_bytes+length(NEW.body); ',1)
                    elif trigger.startswith('CREATE TRIGGER event_delete '):
                        trigger=trigger.replace('BEGIN ','BEGIN UPDATE instance_usage SET events=events-1,body_bytes=body_bytes-length(OLD.body); ',1)
                    elif trigger.startswith('CREATE TRIGGER attempt_insert '):
                        trigger=trigger.replace('BEGIN ','BEGIN UPDATE instance_usage SET attempt_count=attempt_count+1,response_bytes=response_bytes+coalesce(length(CAST(NEW.response AS BLOB)),0); ',1)
                    elif trigger.startswith('CREATE TRIGGER attempt_update '):
                        trigger=trigger.replace('BEGIN ','BEGIN UPDATE instance_usage SET response_bytes=response_bytes+coalesce(length(CAST(NEW.response AS BLOB)),0)-coalesce(length(CAST(OLD.response AS BLOB)),0); ',1)
                    elif trigger.startswith('CREATE TRIGGER attempt_delete '):
                        trigger=trigger.replace('BEGIN ','BEGIN UPDATE instance_usage SET attempt_count=attempt_count-1,response_bytes=response_bytes-coalesce(length(CAST(OLD.response AS BLOB)),0); ',1)
                    conn.execute(text(trigger))
                conn.execute(text('INSERT INTO schema_migrations(version,applied) VALUES(3,:now)'), {'now':time.time()})
    if query('SELECT max(version) version FROM schema_migrations')[0]['version'] != 3:
        raise RuntimeError('Unsupported database schema. Restore the matching application version.')

def query(sql, params=None):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params or {}).mappings()]

def mutate(sql, params=None):
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {}).rowcount
