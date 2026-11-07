"""Resume the fixed 4B comparison in an owned process with durable evidence."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from runtime_json import read_dict_or_archive, write_json_atomic

ROOT=Path(__file__).resolve().parents[2]
state=ROOT/'.runtime/vision-probe-process.json'
output=ROOT/'evidence/V04/model-probe-16frames.json'

def owned_probe():
    expected=os.fsencode(str(ROOT/'vision/scripts/probe_model.py'))
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal(): continue
        try: cmd=(entry/'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError,ProcessLookupError,PermissionError): continue
        if expected in cmd and b'evidence/V04/model-probe-16frames.json' in cmd:
            return int(entry.name)
    return None

def main():
    state.parent.mkdir(exist_ok=True)
    lock=(state.parent/'vision-probe-launch.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX)
    old=read_dict_or_archive(state) or {}
    pid=owned_probe()
    if pid:
        record={**old,'pid':pid,'output':str(output)}
        write_json_atomic(state,record)
        print(json.dumps({'already_running':True,**record},indent=2));return
    verified=json.loads((ROOT/'evidence/V04/official-source-verified.json').read_text())
    assert len(verified)==13 and all(x['verified'] for x in verified)
    previous=read_dict_or_archive(output)
    if previous:
        if previous.get('status')=='completed':
            print('Comparison already completed; see '+str(output));return
        output.replace(output.with_name(f'probe-interrupted-{time.time_ns()}.json'))
    log=ROOT/'evidence/V04/probe-console.txt'
    cmd=[str(ROOT/'vision/.venv/bin/python'),'-u',str(ROOT/'vision/scripts/probe_model.py'),
         '--all','--frames','16','--video-edge','512','--prompt-file','vision/config/review-prompt-v2.txt',
         '--checkpoint','downloads/qwen3-vl-4b-source','--save-quantized',
         '--quantized-output','downloads/qwen3-vl-4b-nf4','--output','evidence/V04/model-probe-16frames.json']
    with log.open('ab') as handle:
        handle.write(f'\n=== 4B comparison started {time.ctime()} ===\n'.encode());handle.flush()
        process=subprocess.Popen(cmd,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,
                                 env={**os.environ,'PYTHONUNBUFFERED':'1'},start_new_session=True)
    record={'pid':process.pid,'started_at':time.time(),'log':str(log),'output':str(output),'command':cmd}
    write_json_atomic(state,record)
    print(json.dumps(record,indent=2))

if __name__=='__main__': main()
