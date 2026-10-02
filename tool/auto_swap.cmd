@echo off
title ZCode RU auto-swap
setlocal
set "LOG=%USERPROFILE%\zcode-swap-result.txt"
set "ASAR=%LOCALAPPDATA%\Programs\ZCode\resources\app.asar"
set "NEW=%LOCALAPPDATA%\Programs\ZCode\resources\app.asar.new-ru"

echo %DATE% %TIME% auto-swap started > "%LOG%"

if not exist "%NEW%" (
  echo [FAIL] patch file missing: %NEW% >> "%LOG%"
  exit /b 1
)

echo %DATE% %TIME% closing ZCode... >> "%LOG%"
taskkill /IM ZCode.exe >> "%LOG%" 2>&1

set /a tries=0
:wait
timeout /t 1 /nobreak >nul
tasklist /FI "IMAGENAME eq ZCode.exe" 2>nul | find /I "ZCode.exe" >nul
if not errorlevel 1 (
  set /a tries+=1
  if %tries% LSS 15 goto wait
  echo %DATE% %TIME% force killing ZCode... >> "%LOG%"
  taskkill /F /IM ZCode.exe >> "%LOG%" 2>&1
  timeout /t 3 /nobreak >nul
)

tasklist /FI "IMAGENAME eq ZCode.exe" 2>nul | find /I "ZCode.exe" >nul
if not errorlevel 1 (
  echo [FAIL] ZCode.exe still running, cannot copy >> "%LOG%"
  exit /b 1
)

echo %DATE% %TIME% copying patch... >> "%LOG%"
copy /Y "%NEW%" "%ASAR%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [FAIL] copy failed >> "%LOG%"
  exit /b 1
)

for %%A in ("%ASAR%") do set "SIZE_A=%%~zA"
for %%B in ("%NEW%") do set "SIZE_N=%%~zB"
if not "%SIZE_A%"=="%SIZE_N%" (
  echo [FAIL] size mismatch %SIZE_A% vs %SIZE_N% >> "%LOG%"
  exit /b 1
)

echo [OK] installed. size=%SIZE_A%. Start ZCode, Settings - Language - Russkiy >> "%LOG%"
exit /b 0
