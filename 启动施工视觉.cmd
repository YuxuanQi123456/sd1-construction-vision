@echo off
chcp 65001 >nul
echo Starting PPE detection and the configured review backend.
wsl.exe --cd "%~dp0." python3 scripts/manage_ppe.py start --wait
if errorlevel 1 goto failed
wsl.exe --cd "%~dp0." python3 scripts/manage_review_api.py start --wait
if errorlevel 1 goto model_failed
start "" "http://127.0.0.1:8767"
exit /b 0
:model_failed
echo Detection is ready. Check config\review-api.local.json and the configured review backend.
start "" "http://127.0.0.1:8767"
pause
exit /b 1
:failed
echo Startup failed. Check .runtime\sitewatch-env\runtime\managed-server.log
pause
exit /b 1
