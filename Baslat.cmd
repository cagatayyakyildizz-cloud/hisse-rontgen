@echo off
setlocal
cd /d "%~dp0"
echo HisseRontgen sunucusu baslatiliyor (http://127.0.0.1:8765)...
start "" http://127.0.0.1:8765
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
pause
