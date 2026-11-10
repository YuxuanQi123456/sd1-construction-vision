@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
echo Starting local annotation page at http://127.0.0.1:8780/web/client-labeler.html
start "Client video labeler server" /min wsl.exe --cd "%ROOT%" python3 -m http.server 8780 --bind 127.0.0.1 --directory .
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8780/web/client-labeler.html"
endlocal
