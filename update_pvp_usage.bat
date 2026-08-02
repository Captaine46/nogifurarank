@echo off
setlocal
chcp 65001 > nul
cd /d "%~dp0"
set "PYTHON=c:\Users\aelin\AppData\Local\Programs\Python\Python39\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%PYTHON%" (
    echo [ERROR] Python was not found: %PYTHON%
    pause
    exit /b 1
)

"%PYTHON%" -u update_pvp_usage.py %*
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%
