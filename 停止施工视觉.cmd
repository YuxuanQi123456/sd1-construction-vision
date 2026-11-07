@echo off
chcp 65001 >nul
wsl.exe --cd "%~dp0." python3 scripts/manage_ppe.py stop
pause
