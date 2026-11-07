"""Start an isolated installed Windows Edge for local browser verification."""
from pathlib import Path
import subprocess
import json

root=Path(__file__).resolve().parents[2]
profile=root/'.runtime/vision-edge-profile'
profile.mkdir(parents=True,exist_ok=True)
win_profile=subprocess.check_output(['wslpath','-w',str(profile)],text=True).strip()
ps="""$p=Start-Process -FilePath 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' -ArgumentList @('--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=9226','--user-data-dir=PROFILE','about:blank') -PassThru; $p.Id""".replace('PROFILE',win_profile.replace("'","''"))
exe='/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
result=subprocess.run([exe,'-NoProfile','-NonInteractive','-Command',ps],capture_output=True,text=True,timeout=20)
record={'returncode':result.returncode,'stdout':result.stdout.strip(),'stderr':result.stderr.strip(),'profile':str(profile),'port':9226}
(root/'.runtime/vision-edge-process.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
