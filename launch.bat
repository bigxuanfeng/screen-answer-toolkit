@echo off
cd /d "%~dp0"
start "" "C:\Program Files\Python312\pythonw.exe" launcher.py
if %errorlevel% neq 0 start "" python launcher.py
