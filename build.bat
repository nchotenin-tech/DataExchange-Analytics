@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   DentalDX - Build EXE
echo ============================================================

set PY=
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo ERROR: Python not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\" (
    echo [1/4] Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 goto err
)

echo [2/4] Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
if errorlevel 1 goto err

echo [3/4] Building exe - this takes 2-5 minutes...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller DentalDX.spec --noconfirm --clean
if errorlevel 1 goto err

echo [4/4] Packaging for delivery...
set "OUT=dist\DentalDX"
if not exist "%OUT%" mkdir "%OUT%"
move /y dist\DentalDX.exe "%OUT%\" >nul
xcopy /e /i /y profiles  "%OUT%\profiles"  >nul
xcopy /e /i /y reference "%OUT%\reference" >nul
if not exist "%OUT%\data" mkdir "%OUT%\data"
for /d %%D in (data\*) do if not exist "%OUT%\data\%%~nxD" mkdir "%OUT%\data\%%~nxD"
copy /y README.md "%OUT%\" >nul 2>&1

echo.
echo ============================================================
echo   DONE: %CD%\%OUT%
echo   Ship the WHOLE DentalDX folder, not just the .exe
echo ============================================================
pause
exit /b 0

:err
echo.
echo *** BUILD FAILED ***
pause
exit /b 1
