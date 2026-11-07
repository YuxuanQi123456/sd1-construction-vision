"""Fetch the pinned official Qwen4B checkpoint for a local quantization trial."""
from pathlib import Path
import hashlib
import json
import shutil
from download_wheels import ROOT, download

cache=ROOT/'downloads/qwen3-vl-4b-source'
cache.mkdir(exist_ok=True)
manifest=ROOT/'vision/config/qwen4b-files.json'
for item in json.loads(manifest.read_text()):
    existing=ROOT/'downloads/qwen3-vl-2b'/item['filename']
    if existing.exists() and existing.stat().st_size==item['size'] and item['size']<20_000_000:
        with existing.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()==item['sha256']:
                shutil.copy2(existing,cache/item['filename'])
download(manifest,cache,8*1024*1024,ROOT/'evidence/V04/official-source-verified.json',workers=32,cleanup_parts=True)
