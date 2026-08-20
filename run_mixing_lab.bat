@echo off
setlocal

cd /d "%~dp0"

python scripts\build_equations.py
if errorlevel 1 goto end

python app.py

:end
endlocal
