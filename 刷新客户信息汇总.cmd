@echo off
setlocal
set "RUNTIME=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies"
"%RUNTIME%\native\powershell\pwsh.exe" -NoProfile -File "%~dp0scripts\run_customer_info_refresh.ps1"
if errorlevel 1 (
  echo Refresh failed. See the error above.
  pause
  exit /b 1
)
echo Refresh complete.
pause
