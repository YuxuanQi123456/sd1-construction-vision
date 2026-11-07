@echo off
chcp 65001 >nul
wsl.exe --cd "%~dp0." python3 scripts/manage_ppe.py stop
wsl.exe --cd "%~dp0." python3 vision/scripts/manage.py stop
pause
