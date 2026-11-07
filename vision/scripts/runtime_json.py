"""Small durable JSON helpers for local process state and experiment evidence."""
import json
from pathlib import Path
import time

def write_json_atomic(path, value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)

def read_dict_or_archive(path):
    path=Path(path)
    if not path.exists(): return None
    try:
        value=json.loads(path.read_text())
        if not isinstance(value,dict): raise ValueError('Expected a JSON object')
        return value
    except (json.JSONDecodeError,ValueError,UnicodeDecodeError):
        path.replace(path.with_name(path.stem+f'.corrupt-{time.time_ns()}'+path.suffix))
        return None
