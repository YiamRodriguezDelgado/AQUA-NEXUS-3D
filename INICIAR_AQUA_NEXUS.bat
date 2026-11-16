@echo off
cd /d "%~dp0"
set AQUA_PORT=8711
echo AQUA NEXUS 3D v4.1 - Astronomicon bilingual UI - puerto 8711
where py >nul 2>&1
if %errorlevel%==0 (py -3 server.py) else (python server.py)
pause
