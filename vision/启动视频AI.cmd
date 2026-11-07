@echo off
chcp 65001 >nul
wsl.exe --cd "%~dp0.." python3 vision/scripts/manage.py start --wait
if errorlevel 1 goto failed
start "" "http://127.0.0.1:8766"
exit /b 0
:failed
echo 启动未完成，请查看项目 .runtime\vision-server.log
pause
