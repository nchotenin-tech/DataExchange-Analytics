@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   DentalDX - Release to GitHub
echo ============================================================
echo.

rem ---------- 1. find python ----------
set PY=
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (
    echo ERROR: Python not found.
    pause
    exit /b 1
)

rem ---------- 2. read VERSION from app.py ----------
for /f "delims=" %%V in ('%PY% tools\version.py') do set VER=%%V
if "%VER%"=="" (
    echo ERROR: cannot read VERSION from app.py
    pause
    exit /b 1
)
echo Version to release : v%VER%
echo.

rem ---------- 3. clear a stale git lock ----------
if exist ".git\index.lock" (
    tasklist /fi "imagename eq git.exe" 2>nul | find /i "git.exe" >nul
    if errorlevel 1 (
        echo Found a stale .git\index.lock from a crashed git - removing it.
        del /f /q ".git\index.lock"
    ) else (
        echo.
        echo *** Another git program is using this folder right now ***
        echo Close VS Code / GitHub Desktop / SourceTree, then run this again.
        pause
        exit /b 1
    )
)

rem ---------- 4. SAFETY: no patient data may be committed ----------
echo [1/5] Checking for patient data files...
git ls-files > "%TEMP%\dx_tracked.txt" 2>nul
findstr /i /c:".xlsx" /c:".xls" "%TEMP%\dx_tracked.txt" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo *** STOP: patient data files are tracked by git! ***
    findstr /i /c:".xlsx" /c:".xls" "%TEMP%\dx_tracked.txt"
    echo.
    echo Remove them first:  git rm --cached "path\to\file.xlsx"
    del "%TEMP%\dx_tracked.txt" >nul 2>&1
    pause
    exit /b 1
)
del "%TEMP%\dx_tracked.txt" >nul 2>&1
echo     OK - no data files tracked.

rem ---------- 4. run tests ----------
echo [2/5] Running smoke test...
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
%PY% tools\smoke_test.py
if errorlevel 1 (
    echo.
    echo *** Smoke test FAILED - fix before releasing ***
    pause
    exit /b 1
)

rem ---------- 5. commit + push ----------
echo [3/5] Committing changes...
git add -A
if errorlevel 1 (
    echo.
    echo *** git add FAILED - nothing was committed ***
    echo See the message above. Common cause: a stale .git\index.lock
    pause
    exit /b 1
)
git diff --cached --stat --compact-summary
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "release v%VER%"
    if errorlevel 1 goto err
) else (
    echo     Nothing new to commit.
)

rem the working tree must be clean now - if not, git add silently failed
for /f "delims=" %%L in ('git status --porcelain') do (
    echo.
    echo *** Files are STILL uncommitted - aborting before tagging ***
    git status --short
    pause
    exit /b 1
)

echo [4/5] Pushing to GitHub...
git push
if errorlevel 1 goto err

rem ---------- 6. tag ----------
echo [5/5] Tagging v%VER% ...
git tag -d v%VER% >nul 2>&1
git push origin :refs/tags/v%VER% >nul 2>&1
git tag v%VER%
if errorlevel 1 goto err
git push origin v%VER%
if errorlevel 1 goto err

rem ---------- 7. verify what actually landed on GitHub ----------
echo.
echo Verifying...
git fetch origin --quiet
for /f "delims=" %%H in ('git rev-parse --short HEAD') do set LOCAL=%%H
for /f "delims=" %%H in ('git rev-parse --short origin/main') do set REMOTE=%%H
for /f "delims=" %%H in ('git rev-list -n 1 --abbrev-commit v%VER%') do set TAGGED=%%H

echo   local HEAD    : %LOCAL%
echo   origin/main   : %REMOTE%
echo   tag v%VER% -^> : %TAGGED%

if not "%LOCAL%"=="%REMOTE%" (
    echo.
    echo   *** WARNING: commit did NOT reach GitHub ***
    echo   GitHub will build OLD code. Run:  git push
    pause
    exit /b 1
)
if not "%LOCAL%"=="%TAGGED%" (
    echo.
    echo   *** WARNING: the tag points at a different commit ***
    pause
    exit /b 1
)
echo   OK - GitHub has the same code as this machine.

echo.
echo ============================================================
echo   DONE. GitHub Actions is building the EXE now.
echo   Takes about 5 minutes.
echo ============================================================
echo.
echo Opening the Actions page...
start "" "https://github.com/nchotenin-tech/DataExchange-Analytics/actions"
echo.
echo When the run turns green, the file will be here:
echo   https://github.com/nchotenin-tech/DataExchange-Analytics/releases/latest
echo.
pause
exit /b 0

:err
echo.
echo *** FAILED - see messages above ***
echo If push was rejected, run:  git pull --rebase   then try again.
pause
exit /b 1
