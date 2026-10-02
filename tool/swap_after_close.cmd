@echo off
rem Swaps the patched app.asar into place once ZCode has fully closed.
rem Usage: swap_after_close.cmd "C:\path\to\app.asar.new-ru"
setlocal EnableDelayedExpansion
set "ASAR=%LOCALAPPDATA%\Programs\ZCode\resources\app.asar"
set "NEW=%~1"
if "%NEW%"=="" (
  echo Usage: swap_after_close.cmd "path\to\app.asar.new-ru"
  echo    or: swap_after_close.cmd "path\to\app.asar.bak-..."   ^(to restore a backup^)
  exit /b 1
)
if not exist "%NEW%" (
  echo File not found: %NEW%
  exit /b 1
)
echo Waiting for ZCode.exe to close... ^(close the app now^)
:wait
tasklist /FI "IMAGENAME eq ZCode.exe" 2>nul | find /I "ZCode.exe" >nul
if not errorlevel 1 (
  timeout /t 2 /nobreak >nul >nul
  goto wait
)
copy /Y "%NEW%" "%ASAR%" >nul
if errorlevel 1 (
  echo Copy failed. Make sure ZCode is fully closed ^(also check the tray icon^) and retry.
  exit /b 1
)
echo Done! Patched app.asar is in place.
echo Start ZCode, open Settings and pick "Русский".
endlocal
