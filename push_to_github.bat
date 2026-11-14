@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   DentalDX - Push code to GitHub (no release)
echo ============================================================
echo.
echo This only uploads the source code.
echo GitHub Actions will build the web app and run the tests.
echo Download the result from the Actions tab (Artifacts).
echo.
echo To publish a real version for users, run release.bat instead.
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git not found. Install Git for Windows first.
    pause
    exit /b 1
)

if exist ".git\index.lock" (
    tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
    if errorlevel 1 (
        echo Removing a stale .git\index.lock
        del /f /q ".git\index.lock"
    ) else (
        echo Another git program is using this folder. Close it and try again.
        pause
        exit /b 1
    )
)

echo [1/4] Checking for patient data files...
git ls-files > "%TEMP%\dx_tracked.txt" 2>nul
findstr /i /c:".xlsx" /c:".xls" "%TEMP%\dx_tracked.txt" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo *** STOP: patient data files are tracked by git ***
    findstr /i /c:".xlsx" /c:".xls" "%TEMP%\dx_tracked.txt"
    del "%TEMP%\dx_tracked.txt" >nul 2>&1
    pause
    exit /b 1
)
del "%TEMP%\dx_tracked.txt" >nul 2>&1
echo     OK - no data files tracked.

echo [2/4] Changes to upload:
git status --short
echo.

set MSG=
set /p MSG=Short message describing the change: 
if "%MSG%"=="" set MSG=update

echo [3/4] Committing...
git add -A
if errorlevel 1 goto err
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%MSG%"
    if errorlevel 1 goto err
) else (
    echo     Nothing new to commit.
)

echo [4/4] Pushing to GitHub...
git push
if errorlevel 1 goto err

echo.
echo Done. Open the Actions tab on GitHub to watch the build.
echo The built files appear under Artifacts when it finishes.
pause
exit /b 0

:err
echo.
echo *** FAILED - see the message above ***
pause
exit /b 1
