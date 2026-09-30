@echo off
title Reality Check
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 server.py
    goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python server.py
    goto :end
)

echo.
echo Python 3 was not found on this PC.
echo Install it from https://www.python.org/downloads/ then run this file again.
echo.
pause

:end
