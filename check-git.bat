@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   DentalDX - Git diagnostic
echo ============================================================
echo.
echo --- where am I ---
cd
echo.
echo --- is this a git repo, and which one ---
git rev-parse --show-toplevel
git rev-parse --git-dir
echo.
echo --- remote ---
git remote -v
echo.
echo --- current branch and commit ---
git branch --show-current
git log --oneline -3
echo.
echo --- HEAD vs origin ---
git fetch origin
git rev-parse --short HEAD
git rev-parse --short origin/main
echo.
echo --- uncommitted changes (should list many files) ---
git status --short
echo.
echo --- what does git add -A stage ---
git add -A
git diff --cached --name-only
echo.
echo --- number of staged files ---
git diff --cached --name-only | find /c /v ""
echo.
echo --- tags ---
git tag -l
echo.
echo --- user identity (commit fails without this) ---
git config user.name
git config user.email
echo.
echo ============================================================
echo   Copy EVERYTHING above and send it back.
echo   Nothing was pushed. Your files are untouched.
echo ============================================================
pause
