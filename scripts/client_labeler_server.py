#!/usr/bin/env python3
"""Local-only HTTP server for the client-video YOLO annotation page."""
from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse


class ClientLabelerHandler(SimpleHTTPRequestHandler):
    server_version = "ClientLabeler/1.0"

    @property
    def root(self) -> Path:
        return self.server.project_root  # type: ignore[attr-defined]

    @property
    def pack(self) -> Path:
        return self.root / "downloads" / "client-labeling-pack"

    def _json(self, payload: object, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _safe_name(self, value: str, suffix: str | None = None) -> str:
        name = Path(unquote(value)).name
        if name != unquote(value).replace("\\", "/").rstrip("/").split("/")[-1]:
            raise ValueError("invalid file name")
        if not name or name in {".", ".."}:
            raise ValueError("invalid file name")
        if suffix and not name.lower().endswith(suffix):
            raise ValueError("invalid file type")
        return name

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404, "file not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _classes(self) -> list[str]:
        names = []
        for line in (self.pack / "classes.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            names.append(parts[1] if len(parts) == 2 and parts[0].isdigit() else line)
        return names

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/info":
            try:
                classes = self._classes()
                image_dir = self.pack / "images" / "train"
                images = sorted(
                    [p.name for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}],
                    key=lambda name: name.casefold(),
                )
                self._json({"status": "ok", "classes": classes, "images": images, "pack": str(self.pack)})
            except Exception as exc:  # pragma: no cover - surfaced in the page
                self._json({"status": "error", "message": str(exc)}, 500)
            return
        if path.startswith("/api/images/"):
            try:
                name = self._safe_name(path[len("/api/images/"):])
                self._send_file(self.pack / "images" / "train" / name)
            except ValueError as exc:
                self._json({"status": "error", "message": str(exc)}, 400)
            return
        if path.startswith("/api/labels/"):
            try:
                name = self._safe_name(path[len("/api/labels/"):], ".txt")
                label_path = self.pack / "labels" / "train" / name
                text = label_path.read_text(encoding="utf-8") if label_path.is_file() else ""
                self._json({"status": "ok", "name": name, "text": text})
            except ValueError as exc:
                self._json({"status": "error", "message": str(exc)}, 400)
            return
        # Serve the static annotation page and project assets from the project root.
        self.directory = str(self.root)
        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/api/labels/"):
            self._json({"status": "error", "message": "unsupported endpoint"}, 404)
            return
        try:
            name = self._safe_name(path[len("/api/labels/"):], ".txt")
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("label file too large")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            text = body.get("text", "")
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            # Keep the server side write limited to valid YOLO rows for this pack.
            classes = self._classes()
            clean = []
            for row in text.splitlines():
                fields = row.split()
                if not fields:
                    continue
                if len(fields) != 5:
                    raise ValueError("each label row must have 5 fields")
                cls = int(fields[0])
                values = [float(item) for item in fields[1:]]
                if not 0 <= cls < len(classes) or any(value < 0 or value > 1 for value in values):
                    raise ValueError("label class or normalized coordinate is out of range")
                clean.append(f"{cls} " + " ".join(f"{value:.6f}" for value in values))
            label_dir = self.pack / "labels" / "train"
            label_dir.mkdir(parents=True, exist_ok=True)
            (label_dir / name).write_text("\n".join(clean) + ("\n" if clean else ""), encoding="utf-8")
            self._json({"status": "ok", "name": name, "rows": len(clean)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"status": "error", "message": str(exc)}, 400)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    root = args.root.resolve()
    pack = root / "downloads" / "client-labeling-pack"
    if not (pack / "classes.txt").is_file():
        raise SystemExit(f"client-labeling-pack is missing: {pack}")
    server = ThreadingHTTPServer((args.host, args.port), ClientLabelerHandler)
    server.project_root = root  # type: ignore[attr-defined]
    print(f"Client labeler: http://{args.host}:{args.port}/web/client-labeler.html", flush=True)
    print(f"Pack: {pack}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
