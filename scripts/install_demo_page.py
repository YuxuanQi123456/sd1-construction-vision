"""Install only the static Chinese guide into an explicitly selected upstream frontend."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--site-packages', type=Path, help='Explicit installed site-packages directory')
    destination.add_argument('--target', type=Path, help='Explicit app/_frontend_dist/sd1-demo destination')
    args = parser.parse_args()
    target = (args.site_packages / 'app/_frontend_dist/sd1-demo') if args.site_packages else args.target
    if target.is_symlink():
        parser.error('Refusing a symlink destination.')
    target = target.resolve()
    if target.name != 'sd1-demo' or target.parent.name != '_frontend_dist' or not (target.parent / 'index.html').is_file():
        parser.error('Target must be an existing upstream _frontend_dist/sd1-demo directory with a sibling index.html.')
    config = json.loads((ROOT / 'config/demo.json').read_text())
    target.mkdir(exist_ok=True)
    installed = []
    for name in ('index.html', 'styles.css', 'app.js'):
        source = ROOT / 'web' / name
        output = target / name
        if output.is_symlink():
            parser.error(f'Refusing symlink file: {output}')
        shutil.copyfile(source, output)
        installed.append({'file': name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
    public_config = target / 'demo-config.json'
    if public_config.is_symlink():
        parser.error(f'Refusing symlink file: {public_config}')
    public_config.write_text(json.dumps({k: config[k] for k in ('email', 'password', 'notice')}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'target': str(target), 'files': installed, 'config': 'Public local-only test credentials from config/demo.json; no token stored', 'url': config['base_url'] + '/sd1-demo/index.html'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
