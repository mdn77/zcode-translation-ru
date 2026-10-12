@echo off
title ZCode RU install + launch test
setlocal EnableDelayedExpansion
set "LOG=%USERPROFILE%\zcode-swap-result.txt"
set "RDIR=%LOCALAPPDATA%\Programs\ZCode\resources"
set "ASAR=%RDIR%\app.asar"
set "NEW=%RDIR%\app.asar.new-ru"
set "PREV=%RDIR%\app.asar.pre-ru-bak"
set "EXE=%LOCALAPPDATA%\Programs\ZCode\ZCode.exe"
set "UPD=%LOCALAPPDATA%\@zcodedesktop-updater"
set "RETRIED=0"

echo %DATE% %TIME% install-with-launchtest started > "%LOG%"

if not exist "%NEW%" (
  echo [FAIL] staged patch missing: %NEW% >> "%LOG%"
  exit /b 1
)

:install
echo %DATE% %TIME% closing ZCode gracefully >> "%LOG%"
taskkill /IM ZCode.exe >> "%LOG%" 2>&1

set /a tries=0
:wait
timeout /t 1 /nobreak >nul
tasklist /FI "IMAGENAME eq ZCode.exe" 2>nul | find /I "ZCode.exe" >nul
if not errorlevel 1 (
  set /a tries+=1
  if !tries! LSS 15 goto wait
  echo %DATE% %TIME% force killing ZCode >> "%LOG%"
  taskkill /F /IM ZCode.exe >> "%LOG%" 2>&1
  timeout /t 3 /nobreak >nul
)

tasklist /FI "IMAGENAME eq ZCode.exe" 2>nul | find /I "ZCode.exe" >nul
if not errorlevel 1 (
  echo [FAIL] ZCode.exe still running, aborting without changes >> "%LOG%"
  exit /b 1
)

rem --- drop any downloaded-but-unapplied update: it would silently
rem     overwrite the patched app.asar on the next launch ---
if exist "%UPD%\pending" rd /s /q "%UPD%\pending" >> "%LOG%" 2>&1
del /q "%UPD%\installer.exe" >> "%LOG%" 2>&1
del /q "%UPD%\current.blockmap" >> "%LOG%" 2>&1

copy /Y "%ASAR%" "%PREV%" >> "%LOG%" 2>&1
copy /Y "%NEW%" "%ASAR%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [FAIL] copy failed, restoring >> "%LOG%"
  copy /Y "%PREV%" "%ASAR%" >> "%LOG%" 2>&1
  exit /b 1
)
echo %DATE% %TIME% patch installed, launching ZCode for the test >> "%LOG%"

start "" "%EXE%"
timeout /t 35 /nobreak >nul

for /f %%C in ('powershell -NoProfile -Command "(Get-Process ZCode -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle} | Measure-Object).Count"') do set "WINCOUNT=%%C"
echo %DATE% %TIME% visible windows: %WINCOUNT% >> "%LOG%"

if "%WINCOUNT%"=="0" (
  echo %DATE% %TIME% NO WINDOW - reverting to original >> "%LOG%"
  taskkill /F /IM ZCode.exe >> "%LOG%" 2>&1
  timeout /t 3 /nobreak >nul
  copy /Y "%PREV%" "%ASAR%" >> "%LOG%" 2>&1
  echo %DATE% %TIME% [REVERTED] original app.asar restored >> "%LOG%"
  start "" "%EXE%"
  exit /b 1
)

rem --- verify the patched file is still in place (nothing overwrote it) ---
for %%A in ("%ASAR%") do set "SIZE_A=%%~zA"
for %%B in ("%NEW%") do set "SIZE_N=%%~zB"
if not "!SIZE_A!"=="!SIZE_N!" (
  echo %DATE% %TIME% [WARN] app.asar size !SIZE_A! differs from patch !SIZE_N! after launch >> "%LOG%"
  if "!RETRIED!"=="0" (
    set "RETRIED=1"
    echo %DATE% %TIME% patch was overwritten after launch - retrying once >> "%LOG%"
    goto install
  )
  echo %DATE% %TIME% [FAIL] patch keeps being overwritten (auto-update?) - giving up >> "%LOG%"
  exit /b 1
)

echo %DATE% %TIME% [SUCCESS] window is up and patch verified in place >> "%LOG%"
echo %DATE% %TIME% open Settings - Language - Russian >> "%LOG%"
schtasks /delete /f /tn "ZCodeRuSwap" >nul 2>&1
schtasks /delete /f /tn "ZCodeRuSwap2" >nul 2>&1
exit /b 0
