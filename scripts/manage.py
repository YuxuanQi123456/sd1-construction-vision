"""Manage only this repository's local OpenConstructionERP process."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime'
KEY = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
# DrvFS here reports 0777 after chmod(0700); PostgreSQL needs Linux permissions.
DATA = Path('/tmp') / ('shuidian-oce-' + KEY)
PORT = 8765
BASE = f'http://127.0.0.1:{PORT}'
PID_FILE = STATE / 'process.json'
LOG_FILE = STATE / 'server.log'
CLI = ROOT / '.venv/bin/openconstructionerp'
VERSION = '19.0.0'
BACKUPS = STATE / 'backups'


def health():
    try:
        with build_opener(ProxyHandler({})).open(BASE + '/api/health', timeout=3) as response:
            return json.load(response)
    except Exception:
        return None


def healthy(result):
    try:
        identity = json.loads((DATA / 'workspace_id.json').read_text())['workspace_id']
        return (isinstance(result, dict) and result.get('status') == 'healthy'
                and result.get('version') == VERSION and result.get('workspace_id') == identity
                and result.get('database') == 'ok' and result.get('frontend_dist_present') is True)
    except (OSError, KeyError, ValueError):
        return False


def runtime_env():
    env = os.environ.copy()
    for key in ('DATABASE_URL', 'DATABASE_SYNC_URL'):
        env.pop(key, None)
    env.update(OE_DATA_DIR=str(DATA), DATA_DIR=str(DATA), OE_CLI_DATA_DIR=str(DATA),
               OE_USE_EMBEDDED_PG='1', PYTHONUNBUFFERED='1', NO_COLOR='1')
    return env


def pg_running():
    file = DATA / 'pgdata/postmaster.pid'
    if not file.exists():
        return False
    pid = int(file.read_text().splitlines()[0])
    try:
        args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return any(b'postgres' in arg for arg in args) and str(DATA / 'pgdata').encode() in args
    except FileNotFoundError:
        return False


def wait_ready(pid):
    for attempt in range(180):
        if own_process() != pid:
            raise SystemExit('Owned server exited; inspect .runtime/server.log')
        result = health()
        if healthy(result):
            print(json.dumps({'health': result}, ensure_ascii=False), flush=True)
            return
        if attempt % 10 == 0:
            print('Waiting for the pinned upstream instance...', flush=True)
        time.sleep(2)
    raise SystemExit('Health timeout; inspect .runtime/server.log before retrying.')


def own_process():
    if not PID_FILE.exists():
        return None
    entry = json.loads(PID_FILE.read_text())
    pid = int(entry['pid'])
    try:
        args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if str(CLI).encode() in args and str(DATA).encode() in args:
            return pid
    except (FileNotFoundError, PermissionError):
        pass
    return None


def start():
    STATE.mkdir(exist_ok=True)
    if DATA.is_symlink() or (DATA.exists() and DATA.stat().st_uid != os.getuid()):
        raise SystemExit('Refusing a runtime directory not owned by this user.')
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    DATA.chmod(0o700)
    pid = own_process()
    if pid:
        wait_ready(pid)
        return
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', PORT))
    except OSError as exc:
        raise SystemExit(f'Cannot reserve local port {PORT}: {exc}')
    with LOG_FILE.open('ab') as log:
        process = subprocess.Popen(
            [str(CLI), 'serve', '--host', '127.0.0.1', '--port', str(PORT),
             '--data-dir', str(DATA), '--no-demo'],
            cwd=ROOT, env=runtime_env(), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    PID_FILE.write_text(json.dumps({'pid': process.pid, 'data_dir': str(DATA), 'url': BASE}) + '\n')
    print(json.dumps({'started_pid': process.pid, 'url': BASE, 'log': str(LOG_FILE),
                      'data_dir': str(DATA)}), flush=True)
    wait_ready(process.pid)


def stop():
    pid = own_process()
    if pid is None:
        print('No owned server process is running.')
        return
    # Signal the verified application PID only; upstream owns its PG cleanup.
    os.kill(pid, signal.SIGTERM)
    for _ in range(120):
        if not own_process() and not pg_running():
            PID_FILE.unlink(missing_ok=True)
            print('Stopped owned application process.')
            return
        time.sleep(0.5)
    raise SystemExit('Graceful shutdown timed out; no force-kill was performed.')


def require_stopped():
    if own_process() or pg_running() or health():
        raise SystemExit('Stop the application and PostgreSQL before backup or restore.')


def backup():
    require_stopped()
    if not (DATA / 'pgdata/PG_VERSION').exists() or not (DATA / 'workspace_id.json').exists():
        raise SystemExit('No initialized project database to archive.')
    BACKUPS.mkdir(parents=True, exist_ok=True)
    path = BACKUPS / (time.strftime('backup-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.tar.gz')
    with tarfile.open(path, 'w:gz', compresslevel=1) as archive:
        archive.add(DATA, arcname='data')
    record = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'size': path.stat().st_size, 'version': VERSION,
              'workspace_id': json.loads((DATA / 'workspace_id.json').read_text())['workspace_id']}
    (STATE / 'latest-backup.json').write_text(json.dumps(record, indent=2) + '\n')
    path.with_suffix('.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)


def restore():
    require_stopped()
    record = json.loads((STATE / 'latest-backup.json').read_text())
    path = (BACKUPS / record['file']).resolve()
    if path.parent != BACKUPS.resolve() or record['version'] != VERSION:
        raise SystemExit('Backup path or version is not valid for this project.')
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise SystemExit('Backup checksum mismatch; runtime left unchanged.')
    staging = Path(tempfile.mkdtemp(prefix=DATA.name + '-restore-', dir='/tmp'))
    with tarfile.open(path, 'r:gz') as archive:
        if any(not (entry.name == 'data' or entry.name.startswith('data/')) for entry in archive.getmembers()):
            raise SystemExit('Unexpected archive root; runtime left unchanged.')
        archive.extractall(staging, filter='data')
    recovered = staging / 'data'
    identity = json.loads((recovered / 'workspace_id.json').read_text())['workspace_id']
    if identity != record['workspace_id'] or not (recovered / 'pgdata/PG_VERSION').is_file():
        raise SystemExit('Backup identity/database missing; runtime left unchanged.')
    # tarfile's safe data filter deliberately discards directory modes. PG
    # requires 0700/0750 even when its parent is private, so restore this before activation.
    (recovered / 'pgdata').chmod(0o700)
    recovered.chmod(0o700)
    previous = None
    if DATA.exists():
        previous = DATA.with_name(DATA.name + '-before-restore-' + uuid.uuid4().hex[:8])
        DATA.rename(previous)
    try:
        recovered.rename(DATA)
        DATA.chmod(0o700)
    except Exception:
        if previous and not DATA.exists():
            previous.rename(DATA)
        raise
    PID_FILE.unlink(missing_ok=True)
    print(json.dumps({'restored': str(path), 'workspace_id': identity,
                      'previous_runtime_preserved': str(previous) if previous else None}))


def inspect_database():
    if not own_process() or not healthy(health()):
        raise SystemExit('Owned instance is not healthy.')
    code = """import json,sys,psycopg2
with psycopg2.connect(host=sys.argv[1],dbname='postgres',user='postgres',connect_timeout=5) as connection:
 with connection.cursor() as cursor:
  cursor.execute('SHOW transaction_isolation')
  isolation=cursor.fetchone()[0]
  cursor.execute('SHOW data_directory')
  directory=cursor.fetchone()[0]
  print(json.dumps({'transaction_isolation':isolation,'data_directory':directory}))
"""
    result = subprocess.run([str(ROOT / '.venv/bin/python'), '-c', code, str(DATA / 'pgdata')],
                            capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    if info['transaction_isolation'] != 'read committed' or Path(info['data_directory']).resolve() != (DATA / 'pgdata').resolve():
        raise SystemExit('Unexpected isolation or database directory.')
    out = ROOT / 'evidence/T04'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'database-isolation.json').write_text(json.dumps(info, indent=2) + '\n')
    print(result.stdout.strip())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status', 'backup', 'restore', 'inspect-db'])
    args = parser.parse_args()
    if args.action == 'start':
        start()
    elif args.action == 'stop':
        stop()
    elif args.action == 'backup':
        backup()
    elif args.action == 'restore':
        restore()
    elif args.action == 'inspect-db':
        inspect_database()
    else:
        result = health()
        print(json.dumps({'pid': own_process(), 'url': BASE, 'health': result,
                          'data_dir': str(DATA)}, ensure_ascii=False, indent=2))
        sys.exit(0 if healthy(result) and own_process() else 1)
