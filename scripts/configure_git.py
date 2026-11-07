"""Set repository-local collaboration defaults; never install, log in or push."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = {
    'core.autocrlf': 'false',
    'pull.ff': 'only',
    'fetch.prune': 'true',
    'push.default': 'simple',
    'user.useConfigOnly': 'true',
}


def git(*arguments):
    return subprocess.check_output(['git', '-C', str(ROOT), *arguments], text=True).strip()


def configured(key):
    result = subprocess.run(['git', '-C', str(ROOT), 'config', '--get', key],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('Cannot read Git configuration')
    return result.stdout.strip() if result.returncode == 0 else None


def configured_urls(key):
    result = subprocess.run(['git', '-C', str(ROOT), 'config', '--get-all', key],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('Cannot read Git remote configuration')
    return result.stdout.splitlines()


def validate_remote(value):
    # Do not persist tokens/passwords, shell transports or arbitrary local paths.
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError('Repository URL cannot contain whitespace or control characters.')
    if re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        return
    url = urlsplit(value)
    port = url.port  # Parse explicitly so malformed or out-of-range ports fail.
    if (url.scheme not in {'https', 'ssh'} or not url.hostname or
            not url.path.strip('/') or url.query or url.fragment or url.password or
            port == 0 or (url.scheme == 'https' and url.username) or
            (url.scheme == 'ssh' and url.username != 'git')):
        raise ValueError('Use a credential-free HTTPS or SSH repository URL.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', help='Your own Git commit name; not a login credential')
    parser.add_argument('--email', help='Your own Git commit email or GitHub noreply email')
    parser.add_argument('--remote', help='An existing private repository HTTPS/SSH URL')
    args = parser.parse_args()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != ROOT:
        parser.error('This script must belong to its own Git repository.')
    if bool(args.name) != bool(args.email):
        parser.error('Provide --name and --email together, or use your existing Git identity.')
    if any('\n' in value or '\r' in value for value in [args.name or '', args.email or '']):
        parser.error('Git identity must use single-line values.')
    if args.remote:
        try:
            validate_remote(args.remote)
        except ValueError as error:
            parser.error(str(error))
        urls = configured_urls('remote.origin.url')
        push_urls = configured_urls('remote.origin.pushurl')
        origin_exists = 'origin' in git('remote').splitlines()
        if (origin_exists and urls != [args.remote]) or (push_urls and push_urls != [args.remote]):
            parser.error('origin has different or multiple fetch/push URLs; it was left unchanged.')
    for key, value in SETTINGS.items():
        git('config', '--local', key, value)
    if args.name:
        git('config', '--local', 'user.name', args.name)
        git('config', '--local', 'user.email', args.email)
    if args.remote and not configured('remote.origin.url'):
        git('remote', 'add', 'origin', args.remote)
    print(json.dumps({'repository': str(ROOT), 'branch': git('branch', '--show-current'),
                      'settings': {key: configured(key) for key in SETTINGS},
                      'author_identity_configured': bool(configured('user.name') and configured('user.email')),
                      'origin_configured': bool(configured('remote.origin.url')),
                      'note': 'Local configuration only. No network login, remote creation or push performed.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
