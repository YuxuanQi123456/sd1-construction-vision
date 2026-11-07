"""Probe downloaded public originals and add a lossless-trimmed 1080p example."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    import av
    import cv2
    import imageio_ffmpeg
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a fresh source verification report')
    root = args.project_root
    manifest = root/'sitewatch/demo-media.json'
    data = json.loads(manifest.read_text())
    source = root/'downloads/vision-samples/hostivar.webm'
    assert digest(source) == '409d0bae14bd98fd767ae8fef2d20a4b21a5726eb0a7a23896824cf12172d301'
    target = root/'downloads/demo-hd/hostivar-1080p-0-8.webm'
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-i', str(source), '-t', '8', '-an', '-c:v', 'copy', str(target)]
    if not target.exists():
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    old = next(e for e in data['entries'] if e['id'] == 'existing-video')
    if not any(e['id'] == 'original-1080' for e in data['entries']):
        data['entries'].insert(-1, {**old, 'id': 'original-1080', 'title': '1080p原画质：轨道施工',
            'relative_path': str(target.relative_to(root)), 'sha256': digest(target), 'bytes': target.stat().st_size,
            'description': '原1080p视频前8秒，视频流直接复制，不缩放、不重编码；原素材仍保留。',
            'derived_from_sha256': digest(source), 'changes': 'First 8 seconds; video packets copied without re-encoding or scaling.'})
    def first_frame(path):
        cap = cv2.VideoCapture(str(path))
        try:
            ok, frame = cap.read()
            assert ok, path
            return frame
        finally:
            cap.release()
    import numpy as np
    assert np.array_equal(first_frame(source), first_frame(target)), 'Trim changed first decoded pixels'
    verified = []
    for entry in data['entries']:
        path = root/entry['relative_path']
        assert digest(path) == entry['sha256']
        if entry['media_type'] == 'video':
            with av.open(str(path)) as container:
                stream = container.streams.video[0]
                metadata = {'width': stream.width, 'height': stream.height,
                            'fps': float(stream.average_rate),
                            'duration_seconds': float(container.duration)/1000000,
                            'codec': stream.codec_context.name}
        else:
            image = cv2.imread(str(path))
            assert image is not None
            metadata = {'width': image.shape[1], 'height': image.shape[0]}
        entry.update(metadata)
        verified.append({key:entry[key] for key in ['id','relative_path','sha256','bytes','width','height']})
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    # Attribution matched by bytes; the metadata is never an inference prompt.
    registry = root/'sitewatch/media-sources.json'
    sources = json.loads(registry.read_text())
    hashes = {x.get('sha256') for x in sources}
    for entry in data['entries']:
        if entry['sha256'] not in hashes:
            sources.append({'file': entry['relative_path'], 'sha256': entry['sha256'], 'bytes': entry['bytes'],
                'author': entry['author'], 'source': entry['source'], 'license': entry['license'],
                'license_url': entry['license_url'], 'nature': entry['description'],
                'changes': entry.get('changes','Publisher original bytes retained; no enhancement or resizing.')})
    registry.write_text(json.dumps(sources, ensure_ascii=False, indent=2)+'\n')
    report = {'passed': True, 'entries': verified, 'trim_command': command,
              'trim_first_decoded_frame_equals_original': True, 'existing_540p_file_unchanged': True,
              'note': 'Pexels provides no publisher SHA; local SHA locks downloaded bytes after source/license verification.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
