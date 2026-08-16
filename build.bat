@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   DentalDX - Build EXE (local)
echo ============================================================
echo.

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem ---------- 1. find python ----------
set PY=
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (
    echo ERROR: Python not found.
    echo Install from https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "delims=" %%V in ('%PY% tools\version.py') do set VER=%%V
echo Python  : %PY%
%PY% --version
echo Version : v%VER%
echo.

rem ---------- 2. virtual environment ----------
echo [1/6] Preparing virtual environment...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 goto err
)
set "VPY=.venv\Scripts\python.exe"

echo [2/6] Installing dependencies...
"%VPY%" -m pip install --upgrade pip -q
"%VPY%" -m pip install -r requirements.txt -q
if errorlevel 1 goto err
"%VPY%" -m pip install pyinstaller -q
if errorlevel 1 goto err

rem ---------- 3. tests ----------
echo [3/6] Running smoke test...
"%VPY%" tools\smoke_test.py
if errorlevel 1 (
    echo.
    echo *** Smoke test FAILED - not building ***
    pause
    exit /b 1
)

rem ---------- 4. build ----------
echo [4/6] Building EXE - takes 2 to 5 minutes...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist package rmdir /s /q package
"%VPY%" -m PyInstaller DentalDX.spec --noconfirm --clean
if errorlevel 1 goto err

if not exist "dist\DentalDX.exe" (
    echo *** dist\DentalDX.exe not found - build failed ***
    pause
    exit /b 1
)

rem ---------- 5. package ----------
echo [5/6] Packaging for distribution...
set "OUT=package\DentalDX"
mkdir "%OUT%" 2>nul
move /y dist\DentalDX.exe "%OUT%\" >nul
xcopy /e /i /y /q profiles  "%OUT%\profiles"  >nul
xcopy /e /i /y /q reference "%OUT%\reference" >nul
xcopy /e /i /y /q docs      "%OUT%\docs"      >nul
copy /y README.md "%OUT%\" >nul
move /y "%OUT%\docs\*.txt" "%OUT%\" >nul 2>&1
"%VPY%" tools\make_data_dirs.py "%OUT%"
if errorlevel 1 goto err

rem ---------- 6. zip ----------
echo [6/6] Creating zip...
set "ZIP=DentalDX-v%VER%-win64.zip"
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'package\DentalDX' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 goto err

for %%F in ("%OUT%\DentalDX.exe") do set SZ=%%~zF
set /a SZMB=!SZ! / 1048576

echo.
echo ============================================================
echo   BUILD OK
echo ============================================================
echo   EXE size    : !SZMB! MB
echo   Folder      : %CD%\%OUT%
echo   Zip to send : %CD%\%ZIP%
echo.
echo   Test it now:
echo     1. put .xlsx files in  %OUT%\data\^<age group^>\
echo     2. run  %OUT%\DentalDX.exe
echo.
echo   Ship the WHOLE folder or the zip - not just the .exe
echo ============================================================
echo.
choice /c YN /n /m "Open the package folder now? [Y/N] "
if errorlevel 2 goto end
start "" "%CD%\%OUT%"

:end
pause
exit /b 0

:err
echo.
echo *** BUILD FAILED - see messages above ***
pause
exit /b 1
