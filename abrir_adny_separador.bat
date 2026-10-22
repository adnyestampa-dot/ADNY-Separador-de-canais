@echo off
REM ADNY Separador (versão Completa)
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
start "ADNY Separador" "%~dp0.venv\Scripts\python.exe" "%~dp0ADNY Separador\run.py"
