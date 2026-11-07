"""Inspect every fixed test label and draw GT previews selected before inference."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output directory")
    args.output.mkdir(parents=True)
    import cv2
    import numpy as np
    import yaml
    root = args.dataset_root.resolve()
    names = yaml.safe_load((root / "data.yaml").read_text())["names"]
    names = dict(enumerate(names)) if isinstance(names, list) else {int(k): v for k, v in names.items()}
    images = sorted((root / "test/images").glob("*"))
    assert len(images) == 90
    classes = defaultdict(list)
    encoded, decoded = defaultdict(list), defaultdict(list)
    annotations = {}
    first_for_class = {}
    for image_path in images:
        image = cv2.imread(str(image_path))
        assert image is not None, str(image_path)
        h, w = image.shape[:2]
        encoded[hashlib.sha256(image_path.read_bytes()).hexdigest()].append(image_path.name)
        pixels = f"{w}x{h}:".encode() + image.tobytes()
        decoded[hashlib.sha256(pixels).hexdigest()].append(image_path.name)
        rows = []
        for line in (root / "test/labels" / (image_path.stem + ".txt")).read_text().splitlines():
            values = line.split()
            if not values:
                continue
            assert len(values) == 5
            cls = int(values[0]); x, y, bw, bh = map(float, values[1:])
            assert cls in names and all(0 <= v <= 1 for v in (x, y, bw, bh)) and bw > 0 and bh > 0
            bbox = [round((x-bw/2)*w), round((y-bh/2)*h), round((x+bw/2)*w), round((y+bh/2)*h)]
            rows.append({"id": cls, "class": names[cls], "bbox_xyxy_pixels": bbox,
                         "width_fraction": bw, "height_fraction": bh, "area_fraction": bw*bh})
            classes[names[cls]].append({"width_fraction": bw, "height_fraction": bh, "area_fraction": bw*bh})
            first_for_class.setdefault(cls, image_path.name)
        annotations[image_path.name] = {"width": w, "height": h, "boxes": rows}
    # These are label-semantic previews, never a subset used to compute metrics.
    selected = sorted(set(first_for_class.values()) | {p.name for p in images[:6]})[:10]
    tiles = []
    palette = [(0,180,0), (0,0,255), (0,150,255), (255,0,0), (255,0,255)]
    for name in selected:
        image = cv2.imread(str(root / "test/images" / name))
        for box in annotations[name]["boxes"]:
            x1, y1, x2, y2 = box["bbox_xyxy_pixels"]
            color = palette[box["id"] % len(palette)]
            cv2.rectangle(image, (x1,y1), (x2,y2), color, 2)
            cv2.putText(image, box["class"], (max(0,x1),max(13,y1-3)), cv2.FONT_HERSHEY_SIMPLEX,0.45,color,1,cv2.LINE_AA)
        cv2.imwrite(str(args.output / (Path(name).stem + "-gt.jpg")), image)
        scale = min(640/image.shape[1],450/image.shape[0])
        thumb = cv2.resize(image, (round(image.shape[1]*scale),round(image.shape[0]*scale)))
        tile = np.full((480,640,3),255,dtype=np.uint8)
        tile[30:30+thumb.shape[0],:thumb.shape[1]] = thumb
        cv2.putText(tile,name[:85],(5,19),cv2.FONT_HERSHEY_SIMPLEX,0.34,(0,0,0),1,cv2.LINE_AA)
        tiles.append(tile)
    if len(tiles)%2:
        tiles.append(np.full_like(tiles[0],255))
    contact = np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)])
    cv2.imwrite(str(args.output / "gt-contact.jpg"),contact)
    stats = {}
    for name, rows in classes.items():
        stats[name] = {"instances":len(rows), **{key+"_quantiles":[float(v) for v in np.quantile([r[key] for r in rows],[0,0.25,0.5,0.75,1])] for key in ["width_fraction","height_fraction","area_fraction"]}}
    result = {"at":datetime.now(timezone.utc).isoformat(),"test_images":90,"names":names,
        "empty_images":sum(not entry["boxes"] for entry in annotations.values()),
        "classes":stats,"exact_encoded_duplicates":[v for v in encoded.values() if len(v)>1],
        "exact_decoded_pixel_duplicates":[v for v in decoded.values() if len(v)>1],
        "duplicate_scope":"Within these 90 test images only; training overlap remains unknown.",
        "preview_selected_before_inference":True,"preview_selection":"First file per class plus first six filenames; max10; metrics always use all90.",
        "preview_files":selected,"annotations":annotations}
    (args.output / "audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"test_images":90,"instances":{k:v['instances'] for k,v in stats.items()},"preview":str(args.output/'gt-contact.jpg')},ensure_ascii=False))


if __name__ == "__main__":
    main()
