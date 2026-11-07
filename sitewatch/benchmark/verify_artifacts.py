"""Independently check recorded native metrics inputs/mappings; do not recompute AP."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Preserve existing verification evidence"
    import yaml
    report = json.loads(args.report.read_text())
    assert report["passed"] and report["images"] == 90
    names = yaml.safe_load((args.dataset_root / "data.yaml").read_text())["names"]
    names = dict(enumerate(names)) if isinstance(names,list) else names
    names = {int(k):v.replace("-","_").lower() for k,v in names.items()}
    checked=[]
    for result in report["results"]:
        if result["status"] == "unsupported":
            assert result["model_id"] == "yolo11n" and result["task"] == "full5" and result["unsupported_classes"] == ["no_vest"]
            continue
        task_dir = args.report.parent / result["model_id"] / result["task"]
        mapping = json.loads((task_dir / "mapping.json").read_text())
        cache = Path(mapping["derived_cache"])
        assert sha(cache / "data.yaml") == mapping["data_yaml_sha256"]
        assert mapping["training_performed"] is False
        gt_counts=Counter()
        for entry in mapping["files"]:
            assert sha(cache/"images/test"/entry["image"]) == entry["image_sha256"]
            assert sha(args.dataset_root/"test/images"/entry["image"]) == entry["image_sha256"]
            label_name=Path(entry["image"]).stem+".txt"
            actual=(cache/"labels/test"/label_name).read_text()
            assert sha(cache/"labels/test"/label_name)==entry["remapped_label_sha256"]
            expected=[]
            for line in (args.dataset_root/"test/labels"/label_name).read_text().splitlines():
                parts=line.split()
                if not parts:continue
                canonical=names[int(parts[0])]
                if canonical in mapping["canonical_to_model_id"]:
                    expected.append(" ".join([str(mapping["canonical_to_model_id"][canonical]),*parts[1:]]))
                    gt_counts[canonical]+=1
            assert actual=="\n".join(expected)+("\n" if expected else ""),label_name
        assert len(mapping["files"])==90
        assert sum(gt_counts.values())==result["denominator_instances"]
        assert set(gt_counts)==set(result["canonical_classes"])
        for entry in result["per_class"]:
            assert entry["instances"]==gt_counts[entry["canonical"]]
            assert entry["raw_id"]==mapping["canonical_to_model_id"][entry["canonical"]]
        predictions=json.loads((task_dir/"validation/predictions.json").read_text())
        allowed={i+1 for i in mapping["canonical_to_model_id"].values()}
        assert all(p["category_id"] in allowed and 0<=p["score"]<=1 for p in predictions)
        checked.append({"model_id":result["model_id"],"task":result["task"],"images":90,
                        "instances":dict(gt_counts),"predictions":len(predictions),
                        "mapping_sha256":sha(task_dir/"mapping.json"),
                        "native_predictions_sha256":sha(task_dir/"validation/predictions.json")})
    assert len(checked)==7
    out={"at":datetime.now(timezone.utc).isoformat(),"native_report_sha256":sha(args.report),
         "checked":checked,"all_mapping_and_byte_checks_passed":True,"mAP_reimplemented":False,
         "model_inference_repeated":False,"passed":True}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed":True,"native_tasks":len(checked),"images_per_task":90,"own_ap_implementation":False}))


if __name__=="__main__":
    main()
