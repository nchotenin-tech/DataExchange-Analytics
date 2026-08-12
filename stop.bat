@echo off
setlocal
set PORT=8765
echo Looking for DentalDX server on port %PORT% ...
set FOUND=
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /r /c:":%PORT% .*LISTENING"') do (
    if not "%%P"=="0" (
        echo   killing PID %%P
        taskkill /f /pid %%P
        set FOUND=1
    )
)
if not defined FOUND echo   nothing running.
echo Done.
pause
