@echo off
chcp 65001 >nul
title ZCode - Russian UI installer / Русификация ZCode
setlocal
set "ROOT=%~dp0"
set "TOOL=%ROOT%tool"
set "LOG=%USERPROFILE%\zcode-swap-result.txt"

echo ============================================================
echo   ZCode Russian UI installer  /  Русификация ZCode
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR / ОШИБКА] Python not found. Install it from https://www.python.org/downloads/
  echo                   Отметьте галочку "Add Python to PATH" при установке.
  pause
  exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR / ОШИБКА] Node.js not found. Install it from https://nodejs.org/
  pause
  exit /b 1
)

rem If this is a git clone, refresh the files first (so the latest
rem translation and patcher are used).
if exist "%ROOT%.git" (
  echo Updating files from the repository... / Обновляю файлы из репозитория...
  git -C "%ROOT%." pull --ff-only >nul 2>&1
)

echo.
echo [1/2] Building the patch (takes 2-4 min) / Собираю патч (2-4 минуты)...
python "%TOOL%\apply_ru_patch.py"
set "PATCH_RC=%ERRORLEVEL%"
rem Exit code 2 is normal: the patch was built and staged, but ZCode was
rem running and locked the file - the installer below completes the swap.
if "%PATCH_RC%"=="0" goto patch_ok
if "%PATCH_RC%"=="2" goto patch_ok
echo.
echo [ERROR / ОШИБКА] Patcher failed with code %PATCH_RC%. See the output above.
pause
exit /b 1

:patch_ok
echo.
echo [2/2] Installing (ZCode will be closed and restarted) / Устанавливаю (ZCode закроется и перезапустится)...
call "%TOOL%\install_with_launchtest.cmd"

echo.
findstr /C:"[SUCCESS]" "%LOG%" >nul 2>&1
if not errorlevel 1 goto ok
echo [WARN] Could not confirm success. See the report: %LOG%
echo        Не удалось подтвердить успех. Смотрите отчёт: %LOG%
pause
exit /b 1

:ok
echo ============================================================
echo   DONE!  /  ГОТОВО!
echo   Start ZCode and open Settings - Language - Russian
echo   Запустите ZCode: Настройки - Язык - Русский
echo ============================================================
pause
exit /b 0
