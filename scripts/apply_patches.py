"""Apply reviewed, hash-guarded adaptations to the pinned upstream install."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'patches/manifest.json').read_text())
dist = importlib.metadata.distribution('openconstructionerp')
if dist.version != manifest['version']:
    raise SystemExit('Upstream version changed; review patches before applying.')
results = []
for entry in manifest['patches']:
    target = Path(dist.locate_file(entry['file']))
    if not target.resolve().is_relative_to((ROOT / '.venv').resolve()):
        raise SystemExit('Wrong Python environment: use this repository .venv/bin/python.')
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest == entry['after_sha256']:
        results.append({'file': entry['file'], 'state': 'already applied', 'sha256': digest})
        continue
    if digest != entry['before_sha256']:
        raise SystemExit(f'Unexpected source hash: {entry["file"]}; refusing to overwrite.')
    source = target.read_text()
    if source.count(entry['needle']) != 1:
        raise SystemExit('Patch anchor is not unique.')
    adapted = source.replace(entry['needle'], entry['insert'] + entry['needle'])
    if hashlib.sha256(adapted.encode()).hexdigest() != entry['after_sha256']:
        raise SystemExit('Adapted source hash does not match manifest.')
    with tempfile.NamedTemporaryFile('w', dir=target.parent, encoding='utf-8', delete=False) as tmp:
        tmp.write(adapted)
        tmp.flush()
        os.fsync(tmp.fileno())
        temporary = Path(tmp.name)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != entry['after_sha256']:
        temporary.unlink()
        raise SystemExit('Temporary patch content failed verification.')
    temporary.chmod(target.stat().st_mode & 0o777)
    temporary.replace(target)
    results.append({'file': entry['file'], 'state': 'applied', 'sha256': entry['after_sha256']})
out = ROOT / 'evidence/T01'
out.mkdir(parents=True, exist_ok=True)
(out / 'patch-application.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results))
