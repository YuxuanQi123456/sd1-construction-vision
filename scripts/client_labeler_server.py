#!/usr/bin/env python3
"""Loopback annotation API with versioned, atomic YOLO label saves."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
from pathlib import Path
import threading
from urllib.parse import unquote, urlparse
import uuid

WRITE_LOCK = threading.RLock()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(raw)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class ClientLabelerHandler(BaseHTTPRequestHandler):
    server_version = 'ClientLabeler/2.0'

    @property
    def root(self) -> Path:
        return self.server.project_root

    @property
    def pack(self) -> Path:
        return self.root / 'downloads/client-labeling-pack'

    def _json(self, payload, status=200):
        self._bytes(json.dumps(payload, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

    def _bytes(self, raw, mime, status=200):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def _name(self, value, label=False):
        name = unquote(value)
        if not name or name in {'.', '..'} or '/' in name or '\\' in name or '\x00' in name:
            raise ValueError('文件名无效')
        suffix = Path(name).suffix.lower()
        image_dir = self.pack / 'images/train'
        if label:
            if suffix != '.txt' or not any((image_dir / (Path(name).stem + ext)).is_file() for ext in ['.jpg', '.jpeg', '.png']):
                raise ValueError('标签没有对应的原始图片')
        elif suffix not in {'.jpg', '.jpeg', '.png'}:
            raise ValueError('图片格式无效')
        return name

    def _classes(self):
        names = []
        for line in (self.pack / 'classes.txt').read_text(encoding='utf-8').splitlines():
            parts = line.strip().split(maxsplit=1)
            if parts:
                names.append(parts[1] if len(parts) == 2 and parts[0].isdigit() else line.strip())
        return names

    def _coverage(self):
        path = self.pack / 'annotation-progress.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == '/api/info':
                images = sorted(p.name for p in (self.pack / 'images/train').iterdir() if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png'})
                self._json({'status': 'ok', 'api_version': 2, 'classes': self._classes(), 'images': images})
            elif path.startswith('/api/images/'):
                name = self._name(path[len('/api/images/'):])
                self._file(self.pack / 'images/train' / name)
            elif path.startswith('/api/labels/'):
                name = self._name(path[len('/api/labels/'):], label=True)
                with WRITE_LOCK:
                    target = self.pack / 'labels/train' / name
                    raw = target.read_bytes() if target.is_file() else b''
                    version = digest(raw)
                    progress = self._coverage().get(name, {})
                    reviewed = progress.get('reviewed_classes', []) if progress.get('version') == version else []
                self._json({'status': 'ok', 'name': name, 'text': raw.decode('utf-8'), 'version': version, 'reviewed_classes': reviewed})
            elif path in {'/', '/web/client-labeler.html', '/web/client-labeler.css', '/web/client-labeler.js'}:
                self._file(self.root / ('web/client-labeler.html' if path == '/' else path.lstrip('/')))
            elif path == '/favicon.ico':
                self._bytes(b'', 'image/x-icon', 204)
            else:
                self._json({'message': '页面不存在'}, 404)
        except (ValueError, OSError) as exc:
            self._json({'message': str(exc)}, 400)

    def _file(self, path):
        if not path.is_file():
            self._json({'message': '文件不存在'}, 404)
        else:
            self._bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/labels/'):
            self._json({'message': '不支持的写入路径'}, 404)
            return
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            self._json({'message': '只接受本机标注页面保存'}, 403)
            return
        try:
            name = self._name(path[len('/api/labels/'):], label=True)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1_000_000:
                raise ValueError('标签请求长度无效')
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(body, dict) or not isinstance(body.get('text'), str):
                raise ValueError('标签请求格式无效')
            classes = self._classes()
            clean = []
            for row in body['text'].splitlines():
                fields = row.split()
                if not fields:
                    continue
                if len(fields) != 5:
                    raise ValueError('每行标签必须有5项')
                cls = int(fields[0])
                values = list(map(float, fields[1:]))
                if not 0 <= cls < len(classes) or any(not math.isfinite(v) or not 0 <= v <= 1 for v in values) or values[2] <= 0 or values[3] <= 0:
                    raise ValueError('类别或坐标无效，原标签未改动')
                clean.append(str(cls) + ' ' + ' '.join(f'{v:.6f}' for v in values))
            reviewed = body.get('reviewed_classes', [])
            if not isinstance(reviewed, list) or any(type(c) is not int or not 0 <= c < len(classes) for c in reviewed):
                raise ValueError('标注完成类别无效')
            raw = ('\n'.join(clean) + ('\n' if clean else '')).encode('utf-8')
            target = self.pack / 'labels/train' / name
            with WRITE_LOCK:
                old = target.read_bytes() if target.is_file() else b''
                if body.get('version') != digest(old):
                    self._json({'message': '标签已在其他窗口更新，或页面版本过旧。请先另存未保存内容，再刷新页面，避免覆盖。'}, 409)
                    return
                previous_progress = self._coverage()
                if raw != old:
                    history = self.pack / 'label-history' / name / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.txt')
                    atomic_bytes(history, old)
                    atomic_bytes(target, raw)
                progress = dict(previous_progress)
                progress[name] = {'version': digest(raw), 'reviewed_classes': sorted(set(reviewed)), 'at': datetime.now(timezone.utc).isoformat()}
                try:
                    atomic_bytes(self.pack / 'annotation-progress.json', json.dumps(progress, ensure_ascii=False, indent=2).encode())
                except OSError:
                    # A failed progress write must not leave a new label revision
                    # behind a reported failed save / stale client version.
                    if raw != old:
                        atomic_bytes(target, old)
                    raise
            self._json({'status': 'ok', 'name': name, 'rows': len(clean), 'version': digest(raw)})
        except (ValueError, TypeError, OSError) as exc:
            self._json({'message': str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8780)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / 'downloads/client-labeling-pack/classes.txt').is_file():
        raise SystemExit('缺少 downloads/client-labeling-pack')
    server = ThreadingHTTPServer((args.host, args.port), ClientLabelerHandler)
    server.project_root = root
    print(f'Client labeler: http://127.0.0.1:{args.port}/web/client-labeler.html', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
