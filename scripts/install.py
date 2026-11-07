"""Reproduce the pinned upstream app, reviewed patches and local demo assets."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / '.venv'
PYTHON = VENV / 'bin/python'


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12+ is required by the pinned upstream application.')
    lock = json.loads((ROOT / 'config/upstream-lock.json').read_text())
    artifact = lock['files'][0]
    wheel = ROOT / 'downloads' / artifact['filename']
    if not wheel.exists():
        if args.verify_only:
            raise SystemExit('Pinned wheel is missing from downloads/.')
        wheel.parent.mkdir(exist_ok=True)
        partial = wheel.with_suffix('.partial')
        urlretrieve(artifact['url'], partial)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != artifact['sha256']:
            raise SystemExit('Downloaded wheel hash mismatch; no packages installed.')
        partial.replace(wheel)
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit('Pinned wheel hash mismatch; refusing to continue.')
    if not args.verify_only:
        if not PYTHON.exists():
            run(sys.executable, '-m', 'venv', VENV)
    site_packages = Path(subprocess.check_output(
        [str(PYTHON), '-c', "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip())
    if not site_packages.resolve().is_relative_to(VENV.resolve()):
        raise SystemExit('Virtual environment package path escaped this repository.')
    if not args.verify_only:
        run(PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', '--timeout', '120',
            wheel, '-r', ROOT / 'config/requirements.lock.txt')
        run(PYTHON, ROOT / 'scripts/apply_patches.py')
        page_installer = ROOT / 'scripts/install_demo_page.py'
        if page_installer.exists():
            run(PYTHON, page_installer, '--site-packages', site_packages)
        source = site_packages / f"openconstructionerp-{lock['version']}.dist-info/licenses"
        (ROOT / 'upstream').mkdir(exist_ok=True)
        for name in ('LICENSE', 'NOTICE'):
            shutil.copyfile(source / name, ROOT / 'upstream' / name)
    run(PYTHON, '-m', 'pip', 'check')
    report = {'upstream_version': lock['version'], 'wheel_sha256': artifact['sha256'],
              'wheel_verified': True, 'patches': []}
    for entry in json.loads((ROOT / 'patches/manifest.json').read_text())['patches']:
        path = site_packages / entry['file']
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry['after_sha256']:
            raise SystemExit('Patch integrity failed: ' + entry['file'])
        report['patches'].append({'file': entry['file'], 'sha256': actual})
    out = ROOT / 'evidence/T04'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'installation-integrity.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
