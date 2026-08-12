@echo off
setlocal
cd /d "%~dp0"
set PORT=8765

echo ============================================================
echo   DentalDX - Dental Data Exchange Analyzer
echo ============================================================

rem --- kill any old server still holding the port ---
set FOUND=
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /r /c:":%PORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        echo Stopping old server ... PID %%P
        taskkill /f /pid %%P >nul 2>&1
        set FOUND=1
    )
)
if defined FOUND (
    echo Old server stopped.
    timeout /t 2 /nobreak >nul
)

set PY=
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo ERROR: Python not found.
    echo Install from https://www.python.org/downloads/
    echo Remember to tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo Using: %PY%
%PY% --version

%PY% -c "import flask, pandas, openpyxl, yaml" >nul 2>&1
if errorlevel 1 (
    echo.
    echo First run - installing dependencies, please wait...
    %PY% -m pip install --upgrade pip -q
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 goto err
    echo Dependencies installed.
)

echo.
%PY% app.py
if errorlevel 1 goto err
exit /b 0

:err
echo.
echo *** FAILED - see messages above ***
pause
exit /b 1
