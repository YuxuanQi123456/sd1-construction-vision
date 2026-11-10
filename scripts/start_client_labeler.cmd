@echo off
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\.runtime\portable-env\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo Starting local annotation page at http://127.0.0.1:8780/web/client-labeler.html
start "Client video labeler server" /min cmd /c ""%PY%" -m http.server 8780 --bind 127.0.0.1 --directory "%ROOT%""
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:8780/web/client-labeler.html"
endlocal
