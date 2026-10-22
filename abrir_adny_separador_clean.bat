@echo off
REM ADNY Separador Clean (UI reduzida)
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
set QT_QPA_PLATFORM=windows
start "ADNY Separador Clean" /D "%~dp0ADNY Separador Clean" "%~dp0.venv\Scripts\python.exe" -u run.py
