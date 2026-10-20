@echo off
REM SeparationScreen Brasil — usa python.exe do venv (com log).
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
start "SeparationScreen Brasil" "%~dp0.venv\Scripts\python.exe" "%~dp0Separatio Clone FAV8\run.py"
