"""Restore four pinned public wheels using resumable, bounded HTTP ranges.

Mirror bytes must match official PyPI SHA256 before they are installed.
"""
import concurrent.futures
import fcntl
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'downloads/vision-wheels'
CHUNK = 1024 * 1024

def download(manifest_path, cache_dir, chunk_size, report_path, workers=16, cleanup_parts=False):
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock = (cache_dir/'download.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest = json.loads(manifest_path.read_text())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    results = []
    for item in manifest:
        target = cache_dir/item['filename']
        def digest(path):
            with path.open('rb') as source:
                return hashlib.file_digest(source, 'sha256').hexdigest()
        if target.exists() and target.stat().st_size == item['size'] and digest(target) == item['sha256']:
            print('Verified cache: '+target.name, flush=True)
            if cleanup_parts:
                for lo in range(0,item['size'],chunk_size):
                    (cache_dir/(item['filename']+'.parts')/str(lo)).unlink(missing_ok=True)
            results.append({**item, 'verified': True}); continue
        parts = cache_dir/(item['filename']+'.parts')
        parts.mkdir(parents=True, exist_ok=True)
        ranges = [(lo, min(lo+chunk_size,item['size'])-1) for lo in range(0,item['size'],chunk_size)]
        def fetch(bounds):
            lo, hi = bounds
            part = parts/str(lo)
            for attempt in range(6):
                size = part.stat().st_size if part.exists() else 0
                if size == hi-lo+1: return
                if size > hi-lo+1:
                    part.replace(parts/(str(lo)+'.invalid'))
                    size = 0
                start = lo+size
                request = urllib.request.Request(item['mirror'],headers={'Range':f'bytes={start}-{hi}'})
                try:
                    with opener.open(request,timeout=25) as response:
                        expected=f'bytes {start}-{hi}/{item["size"]}'
                        whole_file = response.status == 200 and start == 0 and hi == item['size']-1
                        if not whole_file and (response.status != 206 or response.headers.get('Content-Range') != expected):
                            raise RuntimeError('Unexpected HTTP range response')
                        with part.open('ab') as output:
                            while data := response.read(32768): output.write(data)
                    if part.stat().st_size == hi-lo+1: return
                except Exception as error:
                    if attempt == 5: raise RuntimeError(f'{target.name} range {lo}: {error}') from error
                    time.sleep(1)
            raise RuntimeError('Incomplete range')
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for n, _ in enumerate(pool.map(fetch,ranges),1):
                if n % 8 == 0 or n == len(ranges):
                    print(f'{target.name}: {n}/{len(ranges)} ranges',flush=True)
        assembled = target.with_suffix('.verified-part')
        with assembled.open('wb') as output:
            for lo, hi in ranges:
                output.write((parts/str(lo)).read_bytes())
        if digest(assembled) != item['sha256']:
            raise RuntimeError('SHA256 mismatch: '+target.name)
        assembled.replace(target)
        results.append({**item, 'verified':True})
        print('SHA256 verified: '+target.name,flush=True)
        if cleanup_parts:
            # Only discard our exact range files after whole-file verification.
            for lo, hi in ranges:
                (parts/str(lo)).unlink()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results,indent=2)+'\n')

def main():
    download(ROOT/'vision/config/wheels.json',CACHE,CHUNK,ROOT/'evidence/V01/wheels-verified.json')

if __name__ == '__main__': main()
