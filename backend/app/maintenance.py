"""Operator backup/integrity commands. Restore is explicitly offline."""
import argparse
import sqlite3
import time
from pathlib import Path
from .store import backup_to, data, service_lock, engine, initialize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['backup','check','restore'])
    parser.add_argument('path', type=Path)
    parser.add_argument('--offline',action='store_true',help='Acknowledge replacing the stopped workspace from this snapshot.')
    args = parser.parse_args()
    if args.command == 'backup':
        backup_to(args.path)
        print('Consistent backup created and integrity verified.')
    elif args.command == 'restore':
        if not args.offline:
            raise SystemExit('Stop the service and pass --offline to acknowledge restore.')
        if args.path.resolve() == (data / 'hookscope.db').resolve():
            raise SystemExit('Snapshot must differ from the live database.')
        check(args.path)
        with service_lock():
            backup_to(data / f'pre-restore-{time.time_ns()}.db')
            engine.dispose()
            with sqlite3.connect(args.path.resolve().as_uri()+'?mode=ro',uri=True) as source, sqlite3.connect(data / 'hookscope.db') as destination:
                source.backup(destination)
                destination.execute('DELETE FROM sessions')
                destination.execute('DELETE FROM worker_heartbeats')
                destination.commit()
            initialize()
            check(data / 'hookscope.db')
        print('Offline restore completed; previous database backed up and sessions revoked.')
    else:
        check(args.path)


def check(path: Path) -> None:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as conn:
            conn.execute('BEGIN')
            integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
                raise SystemExit('Database verification failed.')
            versions = conn.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall()
            if not versions or versions[-1][0] != 3:
                raise SystemExit('Unsupported schema version. Use the matching application release.')
            for owner,events,body_bytes,response_bytes,attempts in conn.execute('SELECT owner_id,events,body_bytes,response_bytes,attempt_count FROM workspace_usage'):
                actual_events,actual_bytes=conn.execute('SELECT count(*),coalesce(sum(length(e.body)),0) FROM events e JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=?',(owner,)).fetchone()
                actual_attempts,actual_responses=conn.execute('SELECT count(*),coalesce(sum(length(CAST(a.response AS BLOB))),0) FROM attempts a JOIN events e ON e.id=a.event_id JOIN endpoints p ON p.id=e.endpoint_id WHERE p.owner_id=?',(owner,)).fetchone()
                if (events,body_bytes,response_bytes,attempts)!=(actual_events,actual_bytes,actual_responses,actual_attempts):
                    raise SystemExit('Workspace usage counters do not match retained records.')
            instance=conn.execute('SELECT events,body_bytes,response_bytes,attempt_count FROM instance_usage WHERE id=1').fetchone()
            aggregate=conn.execute('SELECT coalesce(sum(events),0),coalesce(sum(body_bytes),0),coalesce(sum(response_bytes),0),coalesce(sum(attempt_count),0) FROM workspace_usage').fetchone()
            if instance!=aggregate:
                raise SystemExit('Instance counters do not match workspace totals.')
        print('Database integrity, foreign keys and schema verified.')


if __name__ == '__main__':
    main()
