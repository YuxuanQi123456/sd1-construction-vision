@echo off
chcp 65001 >nul
echo Starting local vision models. Cold loading can take a few minutes.
wsl.exe --cd "%~dp0." python3 scripts/manage_ppe.py start --wait
if errorlevel 1 goto failed
wsl.exe --cd "%~dp0." python3 vision/scripts/manage.py start --wait
if errorlevel 1 goto model_failed
start "" "http://127.0.0.1:8767"
exit /b 0
:model_failed
echo Detection is ready. Check .runtime\vision-server.log for the regional model.
start "" "http://127.0.0.1:8767"
pause
exit /b 1
:failed
echo Startup failed. Check .runtime\sitewatch-env\runtime\managed-server.log
pause
exit /b 1
