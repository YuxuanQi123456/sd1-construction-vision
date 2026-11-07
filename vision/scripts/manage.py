"""Start/stop only this local Qwen demo; keep logs and pid on the workspace disk."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
STATE = PROJECT/'.runtime/vision-process.json'
LOG = PROJECT/'.runtime/vision-server.log'
URL = 'http://127.0.0.1:8766'

def owned(state):
    try:
        cmd = Path(f'/proc/{state["pid"]}/cmdline').read_bytes().split(b'\0')
        return os.fsencode(str(ROOT/'web_demo_mm.py')) in cmd
    except (FileNotFoundError, KeyError, ProcessLookupError):
        return False

def status():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    result = {'url':URL, 'owned_process_alive':owned(state), 'pid':state.get('pid'), 'ready':False}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'/config',timeout=3) as response:
            config=json.load(response)
        result['ready'] = result['owned_process_alive'] and 'components' in config
    except Exception:
        pass
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['start','status','stop'])
    parser.add_argument('--wait', action='store_true', help='Wait up to 480 seconds for the local page')
    args=parser.parse_args()
    if args.command=='status':
        print(json.dumps(status(),ensure_ascii=False,indent=2));return
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    if args.command=='stop':
        if not owned(state):
            print('No owned vision process to stop.');return
        os.kill(state['pid'],signal.SIGTERM)
        for _ in range(60):
            if not owned(state):break
            time.sleep(.25)
        if owned(state):raise RuntimeError('Vision process has not stopped; it was not force-killed.')
        STATE.unlink(missing_ok=True);print('Stopped owned vision process.');return
    if owned(state):
        if args.wait:
            wait_ready()
        else:
            print(json.dumps(status(),ensure_ascii=False,indent=2))
        return
    interpreter=ROOT/'.venv/bin/python'
    if not interpreter.exists():
        raise RuntimeError('Missing vision/.venv; see vision/README.md installation steps.')
    subprocess.run([str(interpreter),'-c',
                    'import importlib.util; missing=[n for n in ["gradio","transformers","bitsandbytes","accelerate","torchvision","av"] if importlib.util.find_spec(n) is None]; assert not missing, "Missing runtime packages: "+str(missing)'],check=True)
    model=select_checkpoint()
    env=os.environ.copy()
    env.update({'PYTHONUNBUFFERED':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                'GRADIO_ANALYTICS_ENABLED':'False','NO_PROXY':'localhost,127.0.0.1,::1',
                'no_proxy':'localhost,127.0.0.1,::1'})
    LOG.parent.mkdir(exist_ok=True)
    cmd=[str(interpreter),str(ROOT/'web_demo_mm.py'),'--backend','hf','--checkpoint-path',str(model),
         '--load-in-4bit','--server-port','8766','--server-name','127.0.0.1']
    with LOG.open('ab') as log:
        log.write(f'\n=== Vision start {time.strftime("%Y-%m-%d %H:%M:%S")} model={model.name} ===\n'.encode())
        log.flush()
        process=subprocess.Popen(cmd,cwd=PROJECT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    STATE.write_text(json.dumps({'pid':process.pid,'url':URL,'model':str(model),'started_at':time.time()},indent=2)+'\n')
    print(json.dumps({'pid':process.pid,'url':URL,'state':'loading','log':str(LOG)},ensure_ascii=False,indent=2))
    if args.wait:wait_ready()

def wait_ready():
    started=time.monotonic()
    for _ in range(480):
        current=status()
        if current['ready']:
            current['wait_seconds']=round(time.monotonic()-started,3)
            print(json.dumps(current,ensure_ascii=False,indent=2));return
        if not current['owned_process_alive']:
            raise RuntimeError('模型服务已退出，请查看.runtime/vision-server.log。')
        time.sleep(1)
    raise RuntimeError('模型尚未就绪，请查看日志；未重复启动其他模型进程。')

def select_checkpoint():
    for name in ['qwen3-vl-4b-nf4','qwen3-vl-2b-nf4','qwen3-vl-2b']:
        candidate=PROJECT/'downloads'/name
        if all((candidate/f).is_file() and (candidate/f).stat().st_size > 0
               for f in ['config.json','tokenizer.json','model.safetensors']):
            return candidate
    raise RuntimeError('没有完整模型权重；仅保留配置的下载目录不可启动，请先恢复模型。')

if __name__=='__main__':main()
